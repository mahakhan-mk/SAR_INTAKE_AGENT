class AssessmentNotFoundError(Exception):
    pass


class AnalysisRunNotFoundError(Exception):
    pass


class AnalysisRunStatusConflictError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


class IntakeQuestionNotFoundError(LookupError):
    pass


class IntakeQuestionHiddenError(LookupError):
    pass


class IntakeQuestionOptionError(ValueError):
    pass


class AssessmentDocumentNotFoundError(LookupError):
    pass


class DuplicateAssessmentDocumentError(ValueError):
    pass


class DocumentChecklistItemNotFoundError(LookupError):
    pass


class DocumentChecklistRunNotFoundError(LookupError):
    pass
