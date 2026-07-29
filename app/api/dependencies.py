from fastapi import Depends

from app.dependencies import worker as worker_dependencies
from app.dependencies.api import (
    get_ai_analysis_assembler,
    get_ai_analysis_query_service,
    get_analysis_repository,
    get_assessment_repository,
    get_document_checklist_assembler,
    get_document_checklist_query_service,
    get_document_checklist_repository,
    get_document_checklist_review_service,
    get_document_command_service,
    get_document_download_service,
    get_document_query_service,
    get_document_repository,
    get_document_storage,
    get_initial_sar_report_repository,
    get_inherent_risk_query_service,
    get_inherent_risk_assembler,
    get_intake_assembler,
    get_intake_service,
    get_report_download_service,
    get_report_preview_assembler,
    get_report_preview_service,
    get_response_repository,
    get_session,
)

get_azure_executive_summary_client = worker_dependencies.get_azure_executive_summary_client
get_executive_summary_prompt_loader = worker_dependencies.get_executive_summary_prompt_loader
get_inherent_risk_scoring_policy = worker_dependencies.get_inherent_risk_scoring_policy
get_initial_sar_report_renderer = worker_dependencies.get_initial_sar_report_renderer
get_initial_sar_report_storage = worker_dependencies.get_initial_sar_report_storage


def get_inherent_risk_execution_service(
    assessment_repository=Depends(get_assessment_repository),
    analysis_repository=Depends(get_analysis_repository),
    scoring_policy=Depends(get_inherent_risk_scoring_policy),
):
    return worker_dependencies.get_inherent_risk_execution_service(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        scoring_policy=scoring_policy,
    )


def get_document_checklist_execution_service(
    document_repository=Depends(get_document_repository),
    checklist_repository=Depends(get_document_checklist_repository),
    vendor_certification_repository=Depends(worker_dependencies.get_vendor_certification_repository),
    prompt_loader=Depends(get_executive_summary_prompt_loader),
):
    return worker_dependencies.get_document_checklist_execution_service(
        document_repository=document_repository,
        checklist_repository=checklist_repository,
        vendor_certification_repository=vendor_certification_repository,
        prompt_loader=prompt_loader,
    )


def get_executive_summary_service(
    assessment_repository=Depends(get_assessment_repository),
    analysis_repository=Depends(get_analysis_repository),
    inherent_risk_service=Depends(get_inherent_risk_execution_service),
    prompt_loader=Depends(get_executive_summary_prompt_loader),
    llm_client=Depends(get_azure_executive_summary_client),
):
    return worker_dependencies.get_executive_summary_service(
        assessment_repository=assessment_repository,
        analysis_repository=analysis_repository,
        inherent_risk_service=inherent_risk_service,
        prompt_loader=prompt_loader,
        llm_client=llm_client,
    )


def get_initial_sar_report_generation_service(
    preview_service=Depends(get_report_preview_service),
    renderer=Depends(get_initial_sar_report_renderer),
    storage=Depends(get_initial_sar_report_storage),
    repository=Depends(get_initial_sar_report_repository),
    document_repository=Depends(get_document_repository),
):
    return worker_dependencies.get_initial_sar_report_generation_service(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
        document_repository=document_repository,
    )

__all__ = [
    "get_analysis_repository",
    "get_ai_analysis_assembler",
    "get_ai_analysis_query_service",
    "get_assessment_repository",
    "get_azure_executive_summary_client",
    "get_document_checklist_assembler",
    "get_document_checklist_execution_service",
    "get_document_checklist_query_service",
    "get_document_checklist_repository",
    "get_document_checklist_review_service",
    "get_document_command_service",
    "get_document_download_service",
    "get_document_query_service",
    "get_document_repository",
    "get_document_storage",
    "get_executive_summary_prompt_loader",
    "get_executive_summary_service",
    "get_inherent_risk_assembler",
    "get_inherent_risk_execution_service",
    "get_inherent_risk_query_service",
    "get_inherent_risk_scoring_policy",
    "get_initial_sar_report_generation_service",
    "get_initial_sar_report_renderer",
    "get_initial_sar_report_repository",
    "get_initial_sar_report_storage",
    "get_intake_assembler",
    "get_intake_service",
    "get_report_download_service",
    "get_report_preview_assembler",
    "get_report_preview_service",
    "get_response_repository",
    "get_session",
]
