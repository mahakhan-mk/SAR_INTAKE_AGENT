class AssessmentNotFoundError(Exception):
    pass


class AnalysisRunNotFoundError(Exception):
    pass


class AnalysisRunStatusConflictError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


class DocumentChecklistRunNotFoundError(LookupError):
    pass
