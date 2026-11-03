"""Translate service errors at the HTTP boundary."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from filelock import Timeout

from .workspace import InvalidRunId, RunAlreadyExists, RunDataError, RunNotFound

logger = logging.getLogger(__name__)
ERROR_STATUS = {
    InvalidRunId: 400,
    RunNotFound: 404,
    RunDataError: 409,
    RunAlreadyExists: 409,
    Timeout: 503,
}


def register_error_handlers(app: FastAPI) -> None:
    async def handle_error(request: Request, error: Exception) -> JSONResponse:
        status = next(code for kind, code in ERROR_STATUS.items() if isinstance(error, kind))
        detail = (
            "Annotation files are busy; retry shortly."
            if isinstance(error, Timeout)
            else str(error)
        )
        logger.warning("%s %s: %s", request.method, request.url.path, detail)
        return JSONResponse(status_code=status, content={"detail": detail})

    for error_type in ERROR_STATUS:
        app.add_exception_handler(error_type, handle_error)
