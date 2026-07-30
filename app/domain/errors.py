from __future__ import annotations

import re

MAX_FAILURE_SUMMARY_LENGTH = 2000


class AssessmentNotFoundError(Exception):
    pass


class AnalysisRunNotFoundError(Exception):
    pass


class AnalysisRunStatusConflictError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


class DocumentChecklistRunNotFoundError(LookupError):
    pass


class BusinessPreconditionError(ValueError):
    pass


class TransientDependencyError(RuntimeError):
    pass


_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):.*", re.DOTALL)
_LOCAL_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s]+")
_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?(?:\+\w+)?|mysql(?:\+\w+)?|mssql(?:\+\w+)?|amqps?|https?)://[^\s\"'<>]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(password|passwd|pwd|access[_-]?token|api[_-]?key|secret|sig|signature|sas[_-]?token|"
    r"storage[_-]?key|account[_-]?key|sharedaccesssignature)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_AZURE_CONNECTION_STRING_RE = re.compile(
    r"\b(?:DefaultEndpointsProtocol|AccountName|AccountKey|BlobEndpoint|SharedAccessSignature)="
    r"[^;\s]+(?:;[^;\s=]+=[^;\s]+)*",
    re.IGNORECASE,
)
_PROMPT_OR_DOCUMENT_RE = re.compile(
    r"\b(prompt|raw llm response|model response|document text|document content)\b\s*[:=].*",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_failure_summary(
    value: object,
    *,
    fallback: str = "Operation failed.",
    max_length: int = MAX_FAILURE_SUMMARY_LENGTH,
) -> str:
    text = str(value or "").strip()
    fallback = _collapse_whitespace(fallback) or "Operation failed."
    if not text:
        text = fallback
    if "Traceback (most recent call last):" in text:
        text = _TRACEBACK_RE.sub(fallback, text)

    text = _PROMPT_OR_DOCUMENT_RE.sub(fallback, text)
    text = _AZURE_CONNECTION_STRING_RE.sub("[REDACTED_SECRET]", text)
    text = _URL_RE.sub(_redact_url, text)
    text = _BEARER_RE.sub("[REDACTED_TOKEN]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _LOCAL_PATH_RE.sub("[REDACTED_PATH]", text)
    text = _collapse_whitespace(text)
    if not text:
        text = fallback
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "."
    return text or fallback


def _redact_url(match: re.Match[str]) -> str:
    url = match.group(0)
    scheme = url.split("://", 1)[0].lower()
    if scheme.startswith(("postgres", "mysql", "mssql", "amqp")):
        return "[REDACTED_CONNECTION_STRING]"
    if "blob.core.windows.net" in url.lower():
        return "[REDACTED_BLOB_URL]"
    if "?" in url:
        return "[REDACTED_URL]"
    return url


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
