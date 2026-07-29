from __future__ import annotations

from app.application.models import AIAnalysisQuestionRow, AIAnalysisResult, AIAnalysisRunSummary
from app.models.ai_analysis import AIAnalysisQuestionRowRecord, AIAnalysisRunRecord, AIAnalysisViewRecord
from app.models.enums import RiskLevel


class AIAnalysisAssembler:
    def to_dto(self, record: AIAnalysisViewRecord) -> AIAnalysisResult:
        return AIAnalysisResult(
            assessmentId=record.assessment_id,
            latestAnalysisRun=self._to_run_dto(record.latest_run),
            questions=[self._to_question_row_dto(question) for question in record.questions],
        )

    @staticmethod
    def _to_run_dto(record: AIAnalysisRunRecord | None) -> AIAnalysisRunSummary:
        if record is None:
            return AIAnalysisRunSummary(
                analysisRunId=None,
                status=None,
                createdAt=None,
            )
        return AIAnalysisRunSummary(
            analysisRunId=record.analysis_run_id,
            status=record.status,
            createdAt=record.created_at,
        )

    def _to_question_row_dto(self, record: AIAnalysisQuestionRowRecord) -> AIAnalysisQuestionRow:
        return AIAnalysisQuestionRow(
            questionId=record.question_id,
            questionNumber=record.question_number,
            questionText=record.question_text,
            domain=record.domain or "",
            selectedOptionId=record.selected_option_id,
            answerValue=record.answer_value if isinstance(record.answer_value, str) else None,
            riskBand=self._to_risk_level(record.result_risk_level),
            riskScore=record.result_risk_score,
            riskSignal=record.option_risk_signal,
            whyItMatters=record.option_why_it_matters,
            aiExplanation=record.result_explanation,
            confidence=record.result_confidence,
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
