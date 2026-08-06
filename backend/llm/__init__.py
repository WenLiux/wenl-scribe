"""Provider-neutral LLM integration primitives for WENL Scribe."""

from .adapters import (
    SUPPORTED_PROTOCOLS,
    adapter_capabilities,
    get_adapter,
    normalize_models,
    normalize_response,
    protocol_for_config,
)
from .contracts import LLMRequest, NormalizedResponse, PreparedRequest

__all__ = [
    "LLMRequest",
    "NormalizedResponse",
    "PreparedRequest",
    "SUPPORTED_PROTOCOLS",
    "adapter_capabilities",
    "get_adapter",
    "normalize_models",
    "normalize_response",
    "protocol_for_config",
]
