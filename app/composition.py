from __future__ import annotations

from dataclasses import dataclass

try:
    import aio_pika
except ModuleNotFoundError:  # pragma: no cover
    aio_pika = None

from app.assemblers.report_context_assembler import InitialSarReportContextAssembler
from app.config import DEFAULT_INHERENT_RISK_SCORING_POLICY, Settings
from app.database import DatabaseRuntime
from app.llm.client import AzureExecutiveSummaryClient, AzureOpenAIClientSettings
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.messaging.consumer import AssessmentCommandConsumer
from app.messaging.outbox_publisher import OutboxPublisher
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.report_repository import InitialSarReportRepository
from app.repositories.vendor_certification_repository import VendorCertificationRepository
from app.repositories.vendor_reputation_repository import VendorReputationReadRepository
from app.services.document_checklist_service import DocumentChecklistExecutionService
from app.services.document_storage import AzureBlobDocumentStorage
from app.services.executive_summary_service import ExecutiveSummaryService
from app.services.inherent_risk_service import InherentRiskExecutionService
from app.services.initial_sar_report_generation_service import InitialSarReportGenerationService
from app.services.initial_sar_report_renderer import InitialSarReportRenderer
from app.services.initial_sar_report_storage import AzureBlobInitialSarReportStorage
from app.services.report_context_service import InitialSarReportContextService
from app.worker.handlers import AssessmentCommandHandlers
from app.worker.processor import CommandProcessor
from app.worker.registry import CommandRegistry


@dataclass(slots=True)
class ApplicationComponents:
    database: DatabaseRuntime
    consumer: AssessmentCommandConsumer
    outbox_publisher: OutboxPublisher


def build_application(
    *,
    settings: Settings,
    database: DatabaseRuntime,
    rabbitmq_connection: aio_pika.RobustConnection,
) -> ApplicationComponents:
    assessment_repository = AssessmentRepository()
    analysis_repository = AnalysisRepository()
    checklist_repository = DocumentChecklistRepository()
    document_repository = DocumentRepository()
    report_repository = InitialSarReportRepository()
    vendor_certification_repository = VendorCertificationRepository()
    vendor_reputation_repository = VendorReputationReadRepository()

    risk_service = InherentRiskExecutionService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        scoring_policy=DEFAULT_INHERENT_RISK_SCORING_POLICY,
    )
    executive_summary_client = AzureExecutiveSummaryClient(
        AzureOpenAIClientSettings.from_settings(settings)
    )
    executive_summary_service = ExecutiveSummaryService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        inherent_risk_service=risk_service,
        prompt_loader=ExecutiveSummaryPromptLoader(),
        llm_client=executive_summary_client,
    )
    checklist_service = DocumentChecklistExecutionService(
        document_repository=document_repository,
        checklist_repository=checklist_repository,
        vendor_certification_repository=vendor_certification_repository,
        llm_client=executive_summary_client,
    )
    report_context_service = InitialSarReportContextService(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        checklist_repository=checklist_repository,
        document_repository=document_repository,
        inherent_risk_service=risk_service,
        assembler=InitialSarReportContextAssembler(),
        vendor_reputation_repository=vendor_reputation_repository,
    )
    report_generation_service = InitialSarReportGenerationService(
        context_service=report_context_service,
        renderer=InitialSarReportRenderer(),
        storage=AzureBlobInitialSarReportStorage.from_settings(settings),
        repository=report_repository,
        document_repository=document_repository,
        document_storage=AzureBlobDocumentStorage.from_settings(settings),
    )
    handlers = AssessmentCommandHandlers(
        risk_service=risk_service,
        executive_summary_service=executive_summary_service,
        checklist_service=checklist_service,
        report_service=report_generation_service,
        report_repository=report_repository,
    )
    registry = CommandRegistry(handlers)
    processor = CommandProcessor(database.session_factory, settings, registry)
    consumer = AssessmentCommandConsumer(rabbitmq_connection, processor, settings)
    publisher = OutboxPublisher(
        database.session_factory,
        rabbitmq_connection,
        settings,
    )
    return ApplicationComponents(
        database=database,
        consumer=consumer,
        outbox_publisher=publisher,
    )
