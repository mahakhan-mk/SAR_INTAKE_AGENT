from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AssessmentNotFoundError(Exception):
    pass


class AnalysisRunNotFoundError(Exception):
    pass


class AnalysisRunStatusConflictError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


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

    @app.exception_handler(AnalysisRunNotFoundError)
    async def handle_analysis_run_not_found(
        request: Request,
        exc: AnalysisRunNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Analysis run not found."})

    @app.exception_handler(AnalysisRunStatusConflictError)
    async def handle_analysis_run_status_conflict(
        request: Request,
        exc: AnalysisRunStatusConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": f"Analysis run status '{exc.status}' does not allow executive summary generation."},
        )

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
