"""HTTP boundary for local annotation imports."""

from fastapi import FastAPI, HTTPException

from .import_models import ImportRequest
from .import_service import import_run as import_run
from .routers._context import RouterContext
from .workspace import RunAlreadyExists


def register_import_routes(app: FastAPI, ctx: RouterContext) -> None:
    @app.post("/api/import", status_code=201)
    def import_csvs(payload: ImportRequest) -> dict[str, str]:
        try:
            import_run(ctx.project_root, payload.run_id, payload.sources, payload.candidates)
        except RunAlreadyExists:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": payload.run_id}
