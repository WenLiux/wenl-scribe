"""Provider-neutral request and response contracts.

The rest of WENL should operate on these small contracts instead of knowing
whether an upstream service speaks Responses, Chat Completions, or a native
provider protocol.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMRequest:
    """A single non-streaming text generation request."""

    model: str
    prompt: str
    schema: dict[str, Any] | None = None
    schema_name: str = "wenl_response"
    response_mode: str = "auto"
    max_output_tokens: int = 4096
    temperature: float | None = None
    timeout: float = 240.0


@dataclass(frozen=True)
class PreparedRequest:
    """The provider-specific HTTP request created by an adapter."""

    protocol: str
    endpoint: str
    payload: dict[str, Any]
    headers: dict[str, str]
    timeout: float


@dataclass(frozen=True)
class NormalizedResponse:
    """The provider-neutral part of a model response."""

    text: str
    usage: dict[str, Any] | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    raw: Any = None
