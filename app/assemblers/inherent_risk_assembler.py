from app.models.dto import (
    ExecutiveSummaryDTO,
    InherentRiskResponseDTO,
    InherentRiskScreenState,
    InherentRiskValueDTO,
    LinksDTO,
    TopRiskDriverDTO,
)


class InherentRiskAssembler:
    def to_dto(self, state: InherentRiskScreenState) -> InherentRiskResponseDTO:
        return InherentRiskResponseDTO(
            assessmentId=str(state.assessment_id),
            analysisRunId=str(state.analysis_run_id) if state.analysis_run_id is not None else None,
            status=state.status,
            inherentRisk=InherentRiskValueDTO(
                level=state.inherent_risk_level,
                label=state.inherent_risk_level.label,
                highRiskQuestionCount=state.high_risk_question_count,
                sourceText=state.source_text,
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
                aiAnalysis=f"/api/v1/assessments/{state.assessment_id}/ai-analysis",
                reportPreview=f"/api/v1/assessments/{state.assessment_id}/report-preview",
            ),
        )
