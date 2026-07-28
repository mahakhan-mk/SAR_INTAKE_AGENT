from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.assemblers.intake_assembler import IntakeAssembler
from app.assemblers.inherent_risk_assembler import InherentRiskAssembler
from app.assemblers.report_preview_assembler import ReportPreviewAssembler
from app.config import DEFAULT_INHERENT_RISK_SCORING_POLICY, InherentRiskScoringPolicy
from app.database import get_db
from app.llm.client import AzureExecutiveSummaryClient
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.response_repository import ResponseRepository
from app.services.executive_summary_service import ExecutiveSummaryService
from app.services.intake_service import IntakeService
from app.services.inherent_risk_service import InherentRiskService
from app.services.report_service import ReportPreviewService


def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db


def get_assessment_repository() -> AssessmentRepository:
    return AssessmentRepository()


def get_analysis_repository() -> AnalysisRepository:
    return AnalysisRepository()


def get_response_repository() -> ResponseRepository:
    return ResponseRepository()


def get_document_repository() -> DocumentRepository:
    return DocumentRepository()


def get_document_checklist_repository() -> DocumentChecklistRepository:
    return DocumentChecklistRepository()


def get_intake_assembler() -> IntakeAssembler:
    return IntakeAssembler()


def get_inherent_risk_assembler() -> InherentRiskAssembler:
    return InherentRiskAssembler()


def get_report_preview_assembler() -> ReportPreviewAssembler:
    return ReportPreviewAssembler()


def get_inherent_risk_scoring_policy() -> InherentRiskScoringPolicy:
    return DEFAULT_INHERENT_RISK_SCORING_POLICY


def get_executive_summary_prompt_loader() -> ExecutiveSummaryPromptLoader:
    return ExecutiveSummaryPromptLoader()


def get_azure_executive_summary_client() -> AzureExecutiveSummaryClient:
    return AzureExecutiveSummaryClient()


def get_inherent_risk_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    assembler: InherentRiskAssembler = Depends(get_inherent_risk_assembler),
    scoring_policy: InherentRiskScoringPolicy = Depends(get_inherent_risk_scoring_policy),
) -> InherentRiskService:
    return InherentRiskService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        assembler=assembler,
        scoring_policy=scoring_policy,
    )


def get_intake_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    response_repository: ResponseRepository = Depends(get_response_repository),
    assembler: IntakeAssembler = Depends(get_intake_assembler),
) -> IntakeService:
    return IntakeService(
        assessment_repository=assessment_repository,
        response_repository=response_repository,
        assembler=assembler,
    )


def get_executive_summary_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    inherent_risk_service: InherentRiskService = Depends(get_inherent_risk_service),
    prompt_loader: ExecutiveSummaryPromptLoader = Depends(get_executive_summary_prompt_loader),
    llm_client: AzureExecutiveSummaryClient = Depends(get_azure_executive_summary_client),
) -> ExecutiveSummaryService:
    return ExecutiveSummaryService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        inherent_risk_service=inherent_risk_service,
        prompt_loader=prompt_loader,
        llm_client=llm_client,
    )


def get_report_preview_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    checklist_repository: DocumentChecklistRepository = Depends(get_document_checklist_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    assembler: ReportPreviewAssembler = Depends(get_report_preview_assembler),
) -> ReportPreviewService:
    return ReportPreviewService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        checklist_repository=checklist_repository,
        document_repository=document_repository,
        assembler=assembler,
    )
