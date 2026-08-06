"""Common upstream HTTP error classification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorClassification:
    code: str
    retryable: bool


def classify_http_status(status: int, provider_code: object = None) -> ErrorClassification:
    normalized_provider_code = str(provider_code or "").strip()
    if status == 401:
        return ErrorClassification("API_KEY_INVALID", False)
    if status == 403:
        return ErrorClassification("API_PERMISSION_DENIED", False)
    if status == 404:
        return ErrorClassification("API_MODEL_NOT_FOUND", False)
    if status in (408, 504):
        return ErrorClassification("API_TIMEOUT", True)
    if status == 409:
        return ErrorClassification("API_CONFLICT", True)
    if status == 413:
        return ErrorClassification("API_CONTEXT_TOO_LARGE", False)
    if status in (400, 422):
        return ErrorClassification("API_INVALID_REQUEST", False)
    if status == 429:
        return ErrorClassification("API_RATE_LIMITED", True)
    if 500 <= status <= 599:
        return ErrorClassification("API_SERVICE_UNAVAILABLE", True)
    if normalized_provider_code:
        return ErrorClassification("API_PROVIDER_ERROR", False)
    return ErrorClassification("API_SERVICE_UNAVAILABLE", True)
