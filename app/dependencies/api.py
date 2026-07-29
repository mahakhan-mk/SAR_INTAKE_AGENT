from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.assemblers.ai_analysis_assembler import AIAnalysisAssembler
from app.assemblers.document_checklist_assembler import DocumentChecklistAssembler
from app.assemblers.intake_assembler import IntakeAssembler
from app.assemblers.inherent_risk_assembler import InherentRiskAssembler
from app.assemblers.report_preview_assembler import ReportPreviewAssembler
from app.config import get_settings
from app.database import get_db
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.report_repository import InitialSarReportRepository
from app.repositories.response_repository import ResponseRepository
from app.services.document_checklist_service import DocumentChecklistQueryService, DocumentChecklistReviewService
from app.services.document_service import DocumentCommandService, DocumentDownloadService, DocumentQueryService
from app.services.document_storage import AzureBlobDocumentStorage, DocumentStorage
from app.services.ai_analysis_service import AIAnalysisQueryService
from app.services.inherent_risk_service import InherentRiskQueryService
from app.services.intake_service import IntakeService
from app.services.initial_sar_report_storage import InitialSarReportStorage
from app.services.report_service import ReportDownloadService, ReportPreviewService


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


def get_document_storage() -> DocumentStorage:
    return AzureBlobDocumentStorage.from_settings(get_settings())


def get_initial_sar_report_repository() -> InitialSarReportRepository:
    return InitialSarReportRepository()


def get_document_checklist_repository() -> DocumentChecklistRepository:
    return DocumentChecklistRepository()


def get_document_checklist_assembler() -> DocumentChecklistAssembler:
    return DocumentChecklistAssembler()


def get_intake_assembler() -> IntakeAssembler:
    return IntakeAssembler()


def get_inherent_risk_assembler() -> InherentRiskAssembler:
    return InherentRiskAssembler()


def get_ai_analysis_assembler() -> AIAnalysisAssembler:
    return AIAnalysisAssembler()


def get_report_preview_assembler() -> ReportPreviewAssembler:
    return ReportPreviewAssembler()


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


def get_document_checklist_query_service(
    checklist_repository: DocumentChecklistRepository = Depends(get_document_checklist_repository),
) -> DocumentChecklistQueryService:
    return DocumentChecklistQueryService(checklist_repository=checklist_repository)


def get_document_checklist_review_service(
    checklist_repository: DocumentChecklistRepository = Depends(get_document_checklist_repository),
) -> DocumentChecklistReviewService:
    return DocumentChecklistReviewService(checklist_repository=checklist_repository)


def get_document_query_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentQueryService:
    return DocumentQueryService(document_repository=document_repository)


def get_document_command_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentCommandService:
    return DocumentCommandService(document_repository=document_repository, storage=storage)


def get_document_download_service(
    document_repository: DocumentRepository = Depends(get_document_repository),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentDownloadService:
    return DocumentDownloadService(document_repository=document_repository, storage=storage)


from app.dependencies.worker import get_initial_sar_report_storage  # noqa: E402


def get_inherent_risk_query_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    assembler: InherentRiskAssembler = Depends(get_inherent_risk_assembler),
) -> InherentRiskQueryService:
    return InherentRiskQueryService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        assembler=assembler,
    )


def get_ai_analysis_query_service(
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    assembler: AIAnalysisAssembler = Depends(get_ai_analysis_assembler),
) -> AIAnalysisQueryService:
    return AIAnalysisQueryService(
        analysis_repository=analysis_repository,
        assembler=assembler,
    )


def get_report_preview_service(
    assessment_repository: AssessmentRepository = Depends(get_assessment_repository),
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
    checklist_repository: DocumentChecklistRepository = Depends(get_document_checklist_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    inherent_risk_service: InherentRiskQueryService = Depends(get_inherent_risk_query_service),
    assembler: ReportPreviewAssembler = Depends(get_report_preview_assembler),
) -> ReportPreviewService:
    return ReportPreviewService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        checklist_repository=checklist_repository,
        document_repository=document_repository,
        inherent_risk_service=inherent_risk_service,
        assembler=assembler,
    )


def get_report_download_service(
    repository: InitialSarReportRepository = Depends(get_initial_sar_report_repository),
    storage: InitialSarReportStorage = Depends(get_initial_sar_report_storage),
) -> ReportDownloadService:
    return ReportDownloadService(repository=repository, storage=storage)
