"""Application composition for the local annotation workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routers import cell_notes as cell_notes_router
from .routers import clusters as clusters_router
from .routers import column_clusters as column_clusters_router
from .routers import exclusions as exclusions_router
from .routers import exports as exports_router
from .routers import labels as labels_router
from .routers import multi_table as multi_table_router
from .routers import propagation as propagation_router
from .routers import relation_reviews as relation_reviews_router
from .routers import row_verdicts as row_verdicts_router
from .routers import runs as runs_router
from .routers import sources as sources_router
from .routers import stats as stats_router
from .routers import verifications as verifications_router
from .routers._context import RouterContext
from .run_cache import RunCache
from .runs import (
    RunRegistry,
)


def create_app(
    project_root: Path,
    *,
    annotator: str,
    static_dir: Optional[Path] = None,
    server_instance: str | None = None,
) -> FastAPI:
    project_root = Path(project_root).resolve()
    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    if static_dir is None:
        static_dir = Path(__file__).resolve().parents[2] / "frontend" / "labeling"
    static_dir = Path(static_dir).resolve()
    if not static_dir.is_dir():
        raise FileNotFoundError(f"static dir not found: {static_dir}")

    registry = RunRegistry(outputs_dir)
    cache = RunCache(outputs_dir)

    # Resolve once at app-creation time so every request can compare
    # resolved sub-paths against this root cheaply.
    _outputs_root = outputs_dir.resolve()

    app = FastAPI(title="Data-cleaning workbench", docs_url="/api/docs")
    from .http_errors import register_error_handlers

    register_error_handlers(app)

    @app.get("/api/health")
    def health(response: Response) -> dict[str, str]:
        if server_instance:
            response.headers["X-CleanBench-Instance"] = server_instance
        return {"status": "ok"}

    # Defense-in-depth CSP. The labelling UI is self-hosted (modules
    # under /ui/, fetches under /api/), so a strict same-origin policy
    # blocks any future inline-script regression and any third-party
    # asset load. Inline ``style="..."`` attributes are still in use,
    # so style-src keeps 'unsafe-inline'.
    _CSP = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    @app.middleware("http")
    async def _add_csp_header(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    # =====================================================================
    # Register routers (split out of this file - see src/labeling/routers/)
    # =====================================================================

    router_ctx = RouterContext(
        project_root=project_root,
        outputs_dir=outputs_dir,
        static_dir=static_dir,
        annotator=annotator,
        registry=registry,
        cache=cache,
    )
    cell_notes_router.register(app, router_ctx)
    row_verdicts_router.register(app, router_ctx)
    clusters_router.register(app, router_ctx)
    column_clusters_router.register(app, router_ctx)
    labels_router.register(app, router_ctx)
    exclusions_router.register(app, router_ctx)
    exports_router.register(app, router_ctx)
    multi_table_router.register(app, router_ctx)
    propagation_router.register(app, router_ctx)
    runs_router.register(app, router_ctx)
    sources_router.register(app, router_ctx)
    stats_router.register(app, router_ctx)
    verifications_router.register(app, router_ctx)
    relation_reviews_router.register(app, router_ctx)

    from .importing import register_import_routes

    register_import_routes(app, router_ctx)

    # =====================================================================
    # Runs listing + per-run endpoints
    # =====================================================================

    # =====================================================================
    # Static UI + root
    # =====================================================================

    class _NoCacheHTMLStaticFiles(StaticFiles):
        """StaticFiles subclass that forces revalidation on HTML responses.

        HTML files anchor every other static asset on the page (script and
        link tags with cache-bust query strings). If the browser pins a
        stale HTML, it loads stale JS/CSS without the new query strings
        and never picks up new code.

        For ``.html`` (and the bare directory index) we send
        ``Cache-Control: no-cache`` so the browser must revalidate with
        the server on every load. ETag-based 304s mean revalidation is
        cheap when the file hasn't changed. Other assets keep their
        default headers (ETag + Last-Modified, no Cache-Control), which
        is fine because cache-bust query strings invalidate them.
        """

        async def get_response(self, path, scope):  # type: ignore[override]
            response = await super().get_response(path, scope)
            try:
                # Detect HTML by the actual served content-type rather than
                # the request path; that way directory indexes (path="")
                # and any other indirect paths also pick up the header.
                content_type = response.headers.get("content-type", "").lower()
                # Also force revalidation on the JS/CSS bundles. The
                # cache-bust query strings in index.html cover the *first*
                # load of a new build, but operators frequently keep a tab
                # open across deploys; without an explicit Cache-Control
                # the browser may reuse the cached label.js indefinitely
                # (until the tab is hard-refreshed). ETag-based 304s keep
                # the revalidation cost negligible when the file is
                # unchanged.
                if (
                    content_type.startswith("text/html")
                    or content_type.startswith("text/javascript")
                    or content_type.startswith("application/javascript")
                    or content_type.startswith("text/css")
                ):
                    response.headers["Cache-Control"] = "no-cache, must-revalidate"
            except Exception:  # pragma: no cover - defensive
                pass
            return response

    app.mount(
        "/ui",
        _NoCacheHTMLStaticFiles(directory=str(static_dir), html=True),
        name="ui",
    )

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")

    return app
