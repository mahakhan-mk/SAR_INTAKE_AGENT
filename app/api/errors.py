from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AssessmentNotFoundError(Exception):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AssessmentNotFoundError)
    async def handle_assessment_not_found(
        request: Request,
        exc: AssessmentNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Assessment not found."})
