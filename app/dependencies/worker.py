from app.config import DEFAULT_INHERENT_RISK_SCORING_POLICY, InherentRiskScoringPolicy, get_settings
from app.llm.client import AzureExecutiveSummaryClient
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.report_repository import InitialSarReportRepository
from app.repositories.vendor_certification_repository import VendorCertificationRepository
from app.services.document_checklist_service import DocumentChecklistExecutionService
from app.services.executive_summary_service import ExecutiveSummaryService
from app.services.initial_sar_report_generation_service import InitialSarReportGenerationService
from app.services.initial_sar_report_renderer import InitialSarReportRenderer
from app.services.initial_sar_report_storage import AzureBlobInitialSarReportStorage, InitialSarReportStorage
from app.services.inherent_risk_service import InherentRiskExecutionService
from app.services.report_service import ReportPreviewService


def get_initial_sar_report_renderer() -> InitialSarReportRenderer:
    return InitialSarReportRenderer()


def get_inherent_risk_scoring_policy() -> InherentRiskScoringPolicy:
    return DEFAULT_INHERENT_RISK_SCORING_POLICY


def get_executive_summary_prompt_loader() -> ExecutiveSummaryPromptLoader:
    return ExecutiveSummaryPromptLoader()


def get_azure_executive_summary_client() -> AzureExecutiveSummaryClient:
    return AzureExecutiveSummaryClient()


def get_vendor_certification_repository() -> VendorCertificationRepository:
    return VendorCertificationRepository()


def get_inherent_risk_execution_service(
    *,
    assessment_repository: AssessmentRepository | None = None,
    analysis_repository: AnalysisRepository | None = None,
    scoring_policy: InherentRiskScoringPolicy | None = None,
) -> InherentRiskExecutionService:
    return InherentRiskExecutionService(
        assessment_repository=assessment_repository or AssessmentRepository(),
        analysis_repository=analysis_repository or AnalysisRepository(),
        scoring_policy=scoring_policy or get_inherent_risk_scoring_policy(),
    )


def get_document_checklist_execution_service(
    *,
    document_repository: DocumentRepository | None = None,
    checklist_repository: DocumentChecklistRepository | None = None,
    vendor_certification_repository: VendorCertificationRepository | None = None,
    prompt_loader: ExecutiveSummaryPromptLoader | None = None,
) -> DocumentChecklistExecutionService:
    return DocumentChecklistExecutionService(
        document_repository=document_repository or DocumentRepository(),
        checklist_repository=checklist_repository or DocumentChecklistRepository(),
        vendor_certification_repository=vendor_certification_repository or VendorCertificationRepository(),
        prompt_loader=prompt_loader or get_executive_summary_prompt_loader(),
    )


def get_executive_summary_service(
    *,
    assessment_repository: AssessmentRepository | None = None,
    analysis_repository: AnalysisRepository | None = None,
    inherent_risk_service: InherentRiskExecutionService | None = None,
    prompt_loader: ExecutiveSummaryPromptLoader | None = None,
    llm_client: AzureExecutiveSummaryClient | None = None,
) -> ExecutiveSummaryService:
    return ExecutiveSummaryService(
        assessment_repository=assessment_repository or AssessmentRepository(),
        analysis_repository=analysis_repository or AnalysisRepository(),
        inherent_risk_service=inherent_risk_service or get_inherent_risk_execution_service(),
        prompt_loader=prompt_loader or get_executive_summary_prompt_loader(),
        llm_client=llm_client or get_azure_executive_summary_client(),
    )


def get_initial_sar_report_storage() -> InitialSarReportStorage:
    return AzureBlobInitialSarReportStorage.from_settings(get_settings())


def get_initial_sar_report_generation_service(
    *,
    preview_service: ReportPreviewService,
    renderer: InitialSarReportRenderer | None = None,
    storage: InitialSarReportStorage | None = None,
    repository: InitialSarReportRepository | None = None,
    document_repository: DocumentRepository | None = None,
) -> InitialSarReportGenerationService:
    return InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer or get_initial_sar_report_renderer(),
        storage=storage or get_initial_sar_report_storage(),
        repository=repository or InitialSarReportRepository(),
        document_repository=document_repository or DocumentRepository(),
    )
