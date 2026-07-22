from __future__ import annotations

from app.models.ai_analysis import AIAnalysisQuestionRowRecord, AIAnalysisRunRecord, AIAnalysisViewRecord
from app.models.dto import AIAnalysisQuestionRowDTO, AIAnalysisResponseDTO, AIAnalysisRunSummaryDTO
from app.models.enums import RiskLevel


class AIAnalysisAssembler:
    def to_dto(self, record: AIAnalysisViewRecord) -> AIAnalysisResponseDTO:
        return AIAnalysisResponseDTO(
            assessmentId=str(record.assessment_id),
            latestAnalysisRun=self._to_run_dto(record.latest_run),
            questions=[self._to_question_row_dto(question) for question in record.questions],
        )

    @staticmethod
    def _to_run_dto(record: AIAnalysisRunRecord | None) -> AIAnalysisRunSummaryDTO:
        if record is None:
            return AIAnalysisRunSummaryDTO(
                analysisRunId=None,
                status=None,
                createdAt=None,
            )
        return AIAnalysisRunSummaryDTO(
            analysisRunId=str(record.analysis_run_id),
            status=record.status,
            createdAt=record.created_at,
        )

    def _to_question_row_dto(self, record: AIAnalysisQuestionRowRecord) -> AIAnalysisQuestionRowDTO:
        return AIAnalysisQuestionRowDTO(
            questionId=str(record.question_id),
            questionNumber=record.question_number,
            questionText=record.question_text,
            domain=record.domain or "",
            selectedOptionId=str(record.selected_option_id) if record.selected_option_id is not None else None,
            answerValue=record.answer_value if isinstance(record.answer_value, str) else None,
            riskBand=self._to_risk_level(record.result_risk_level),
            riskScore=record.result_risk_score,
            riskSignal=record.option_risk_signal,
            whyItMatters=record.option_why_it_matters,
            reviewerRemarks=record.reviewer_remarks,
        )

    @staticmethod
    def _to_risk_level(value: str | None) -> RiskLevel | None:
        if value is None:
            return None
        try:
            return RiskLevel(value)
        except ValueError:
            return None
