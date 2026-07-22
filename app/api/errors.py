from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AssessmentNotFoundError(Exception):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    from app.services.intake_service import (
        IntakeQuestionHiddenError,
        IntakeQuestionNotFoundError,
        IntakeQuestionOptionError,
    )

    @app.exception_handler(AssessmentNotFoundError)
    async def handle_assessment_not_found(
        request: Request,
        exc: AssessmentNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Assessment not found."})

    @app.exception_handler(IntakeQuestionNotFoundError)
    async def handle_intake_question_not_found(
        request: Request,
        exc: IntakeQuestionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Question not found."})

    @app.exception_handler(IntakeQuestionHiddenError)
    async def handle_intake_question_hidden(
        request: Request,
        exc: IntakeQuestionHiddenError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Question is not visible."})

    @app.exception_handler(IntakeQuestionOptionError)
    async def handle_intake_question_option_error(
        request: Request,
        exc: IntakeQuestionOptionError,
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "Selected option is invalid for the question."})
