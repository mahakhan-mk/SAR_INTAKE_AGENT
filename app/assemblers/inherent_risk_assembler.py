from app.application.models import (
    InherentRiskExecutiveSummary,
    InherentRiskLinks,
    InherentRiskResponse,
    InherentRiskScreenState,
    InherentRiskTopRiskDriver,
    InherentRiskValue,
)


SOURCE_TEXT = "Derived from SAR triage questions."


class InherentRiskAssembler:
    def to_dto(self, state: InherentRiskScreenState) -> InherentRiskResponse:
        assessment_id = str(state.assessment_id)
        return InherentRiskResponse(
            assessmentId=state.assessment_id,
            analysisRunId=state.analysis_run_id,
            status=state.status,
            inherentRisk=InherentRiskValue(
                level=state.inherent_risk_level,
                label=state.inherent_risk_level.label,
                highRiskQuestionCount=state.high_risk_question_count,
                sourceText=SOURCE_TEXT,
            ),
            topRiskDrivers=[
                InherentRiskTopRiskDriver(domain=driver.domain, level=driver.level)
                for driver in state.top_risk_drivers
            ],
            executiveSummary=InherentRiskExecutiveSummary(
                text=state.executive_summary_text,
                status=state.executive_summary_status,
                generatedAt=state.executive_summary_generated_at,
            ),
            links=InherentRiskLinks(
                aiAnalysis=f"/api/v1/assessments/{assessment_id}/ai-analysis",
                reportPreview=f"/api/v1/assessments/{assessment_id}/report-preview",
            ),
        )
