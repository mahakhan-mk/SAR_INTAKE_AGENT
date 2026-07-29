INITIAL_SAR_REPORT_QUESTION_CODE_TO_FIELD_NAME: dict[str, str] = {
    "what_business_unit_the_request_is_from": "businessContactDetails.businessUnit",
    "sponsoring_partner": "businessContactDetails.sponsorBusinessOwner",
    "when_is_the_expected_launch_date": "solutionOverview.launchDate",
    "what_is_the_function_and_purpose_of_the_application": "solutionOverview.businessFunctionSolutionOverview",
    "hosting_solution": "hosting.hostingModel",
    "solution_hosted_by": "hosting.hostedBy",
    "solution_accessed_by": "hosting.accessedBy",
    "where_does_the_data_reside_and_type_of_data_housed_or_processed_by_the_solution": "dataHosted.dataResidency",
    "what_is_the_information_classification_for_data_confidentiality": "dataHosted.confidentiality",
    "what_is_the_information_classification_for_data_integrity": "dataHosted.integrity",
    "please_describe_the_data_flows_of_the_solution": "dataFlow.dataFlow",
    "business_continuity_rating": "businessContinuity.businessContinuityRating",
    "what_are_the_required_or_expected_recovery_point_object_rpo_recovery_time_objective_rto_see_techology_definitions": "businessContinuity.rpoRto",
    "what_are_the_backup_and_restore_requirements": "businessContinuity.backupAndRestore",
    "has_a_security_assessment_on_3rd_parties_been_performed_and_reviewed_regularly_if_yes_please_provide_copy_of_the_report_i_e_soc_2_iso27k": "thirdPartyMeasures.thirdPartyAssessment",
    "is_there_an_sla_document_available_if_yes_please_provide_for_review": "thirdPartyMeasures.sla",
}

__all__ = ["INITIAL_SAR_REPORT_QUESTION_CODE_TO_FIELD_NAME"]
