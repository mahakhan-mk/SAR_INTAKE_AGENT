from app.models.dto import (
    ExecutiveSummaryDTO,
    InherentRiskResponseDTO,
    InherentRiskScreenState,
    InherentRiskValueDTO,
    LinksDTO,
    TopRiskDriverDTO,
)

SOURCE_TEXT = "Derived from SAR triage questions."


class InherentRiskAssembler:
    def to_dto(self, state: InherentRiskScreenState) -> InherentRiskResponseDTO:
        assessment_id = str(state.assessment_id)
        analysis_run_id = str(state.analysis_run_id) if state.analysis_run_id is not None else None
        return InherentRiskResponseDTO(
            assessmentId=assessment_id,
            analysisRunId=analysis_run_id,
            status=state.status,
            inherentRisk=InherentRiskValueDTO(
                level=state.inherent_risk_level,
                label=state.inherent_risk_level.label,
                highRiskQuestionCount=state.high_risk_question_count,
                sourceText=SOURCE_TEXT,
            ),
            topRiskDrivers=[
                TopRiskDriverDTO(domain=driver.domain, level=driver.level)
                for driver in state.top_risk_drivers
            ],
            executiveSummary=ExecutiveSummaryDTO(
                text=state.executive_summary_text,
                status=state.executive_summary_status,
                generatedAt=state.executive_summary_generated_at,
            ),
            links=LinksDTO(
                aiAnalysis=f"/api/v1/assessments/{assessment_id}/ai-analysis",
                reportPreview=f"/api/v1/assessments/{assessment_id}/report-preview",
            ),
        )
