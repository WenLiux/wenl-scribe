"""Explicit protocol adapters for summary model providers.

Provider names and wire protocols are intentionally separate.  A provider can
offer both a native endpoint and an OpenAI-compatible endpoint, while several
providers can share the same OpenAI Chat Completions adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .contracts import LLMRequest, NormalizedResponse, PreparedRequest


SUPPORTED_PROTOCOLS = {
    "openai_responses",
    "openai_chat",
    "gemini_openai",
    "sensenova_native",
    "sensenova_compatible",
    "ollama",
}

PROVIDER_PROTOCOLS = {
    "openai": {"openai_responses", "openai_chat"},
    "gemini": {"gemini_openai"},
    "sensenova": {"sensenova_native", "sensenova_compatible"},
    "compatible": {"openai_chat", "ollama"},
}


def _base_url(config: dict[str, Any]) -> str:
    return str(config.get("base_url") or "").strip().rstrip("/")


def _endpoint(config: dict[str, Any], name: str, suffix: str) -> str:
    endpoints = config.get("endpoints")
    if isinstance(endpoints, dict):
        configured = str(endpoints.get(name) or "").strip().rstrip("/")
        if configured:
            return configured
    base = _base_url(config)
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def _headers(config: dict[str, Any]) -> dict[str, str]:
    api_key = str(config.get("api_key") or "")
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _standard_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是忠实的视频内容编辑。只输出合法 JSON，不要使用 Markdown。"},
        {"role": "user", "content": prompt},
    ]


def _sense_messages(prompt: str) -> list[dict[str, list[dict[str, str]]]]:
    return [
        {"role": "system", "content": [{"type": "text", "text": "你是忠实的视频内容编辑。只输出合法 JSON，不要使用 Markdown。"}]},
        {"role": "user", "content": [{"type": "text", "text": prompt}]},
    ]


def _schema_format(request: LLMRequest) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": request.schema_name,
            "strict": True,
            "schema": request.schema or {"type": "object"},
        },
    }


def _response_mode(config: dict[str, Any], request: LLMRequest, default: str) -> str:
    if request.response_mode != "auto":
        return request.response_mode
    configured = str(config.get("response_mode") or "").strip()
    if configured:
        return configured
    capabilities = config.get("capabilities")
    if isinstance(capabilities, dict):
        supported = capabilities.get("structured_output")
        if supported:
            return str(supported)
    return default


class ProviderAdapter(ABC):
    protocol = ""

    @abstractmethod
    def prepare(self, config: dict[str, Any], request: LLMRequest) -> PreparedRequest:
        raise NotImplementedError

    def parse(self, result: Any) -> NormalizedResponse:
        return normalize_response(result)

    def capabilities(self, config: dict[str, Any]) -> dict[str, Any]:
        return adapter_capabilities(self.protocol)

    def models_endpoint(self, config: dict[str, Any]) -> str:
        """Return the OpenAI-style model discovery endpoint for this adapter."""

        endpoints = config.get("endpoints")
        if isinstance(endpoints, dict):
            configured = str(endpoints.get("models") or "").strip().rstrip("/")
            if configured:
                return configured
        if self.protocol == "ollama":
            base = _base_url(config)
            if base.endswith("/v1"):
                base = base[:-3]
            return f"{base}/api/tags"
        return _endpoint(config, "models", "/models")

    def models_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return _headers(config)


class OpenAIResponsesAdapter(ProviderAdapter):
    protocol = "openai_responses"

    def prepare(self, config: dict[str, Any], request: LLMRequest) -> PreparedRequest:
        mode = _response_mode(config, request, "json_schema")
        text_format: dict[str, Any]
        if mode == "json_object":
            text_format = {"type": "json_object"}
        else:
            text_format = {
                "type": "json_schema",
                "name": request.schema_name,
                "schema": request.schema or {"type": "object"},
                "strict": True,
            }
        payload = {
            "model": request.model,
            "input": request.prompt,
            "store": False,
            "text": {"format": text_format},
        }
        return PreparedRequest(
            protocol=self.protocol,
            endpoint=_endpoint(config, "responses", "/responses"),
            payload=payload,
            headers=_headers(config),
            timeout=request.timeout,
        )


class OpenAIChatAdapter(ProviderAdapter):
    protocol = "openai_chat"

    def __init__(self, protocol: str = "openai_chat"):
        self.protocol = protocol

    def prepare(self, config: dict[str, Any], request: LLMRequest) -> PreparedRequest:
        # Compatibility gateways are not consistent about response_format.
        # Prompt-level JSON is the safest common denominator and is also what
        # the standalone SenseNova tester sends by default.
        default_mode = "prompt_json"
        mode = _response_mode(config, request, default_mode)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _standard_messages(request.prompt),
        }
        if request.max_output_tokens:
            base = _base_url(config)
            token_field = "max_completion_tokens" if self.protocol == "sensenova_compatible" and "/compatible-mode/" in base else "max_tokens"
            payload[token_field] = request.max_output_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if self.protocol == "sensenova_compatible":
            payload["stream"] = False
            reasoning_effort = str(config.get("reasoning_effort") or "").strip().lower()
            if reasoning_effort in {"none", "low", "medium", "high"}:
                payload["reasoning_effort"] = reasoning_effort
        if self.protocol == "gemini_openai":
            payload["reasoning_effort"] = str(config.get("reasoning_effort") or "low")
        if mode == "json_schema":
            payload["response_format"] = _schema_format(request)
        elif mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return PreparedRequest(
            protocol=self.protocol,
            endpoint=_endpoint(config, "chat", "/chat/completions"),
            payload=payload,
            headers=_headers(config),
            timeout=request.timeout,
        )


class SenseNovaNativeAdapter(ProviderAdapter):
    protocol = "sensenova_native"

    def prepare(self, config: dict[str, Any], request: LLMRequest) -> PreparedRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _sense_messages(request.prompt),
            "max_new_tokens": request.max_output_tokens,
            "stream": False,
            "temperature": 0.2 if request.temperature is None else request.temperature,
            "top_p": 0.7,
        }
        return PreparedRequest(
            protocol=self.protocol,
            endpoint=_endpoint(config, "chat", "/chat-completions"),
            payload=payload,
            headers=_headers(config),
            timeout=request.timeout,
        )


def protocol_for_config(config: dict[str, Any]) -> str:
    """Return the explicit protocol, with a legacy-only migration fallback."""

    explicit = str(config.get("protocol") or "").strip()
    if explicit in SUPPORTED_PROTOCOLS:
        provider = str(config.get("provider") or "").strip()
        supported = PROVIDER_PROTOCOLS.get(provider)
        if supported and explicit not in supported:
            raise ValueError(f"供应商 {provider} 不支持协议 {explicit}")
        return explicit
    provider = str(config.get("provider") or "").strip()
    if provider == "openai":
        return "openai_responses"
    if provider == "gemini":
        return "gemini_openai"
    if provider == "sensenova":
        # Existing v0.7 configs did not store a protocol.  This fallback is
        # only for migration; newly saved configs always store protocol.
        base = _base_url(config)
        return "sensenova_native" if base.endswith("/llm") or base.endswith("/llm/chat-completions") else "sensenova_compatible"
    if provider == "compatible":
        return "ollama" if "11434" in _base_url(config) else "openai_chat"
    raise ValueError(f"不支持的总结协议：{explicit or provider or 'unknown'}")


def get_adapter(config: dict[str, Any]) -> ProviderAdapter:
    protocol = protocol_for_config(config)
    if protocol == "openai_responses":
        return OpenAIResponsesAdapter()
    if protocol == "openai_chat":
        return OpenAIChatAdapter()
    if protocol == "gemini_openai":
        return OpenAIChatAdapter(protocol)
    if protocol == "sensenova_native":
        return SenseNovaNativeAdapter()
    if protocol in ("sensenova_compatible", "ollama"):
        return OpenAIChatAdapter(protocol)
    raise ValueError(f"不支持的总结协议：{protocol}")


def adapter_capabilities(protocol: str) -> dict[str, Any]:
    defaults = {
        "openai_responses": {"structured_output": "json_schema", "models": True, "stream": False, "usage": True},
        # A generic compatibility endpoint cannot be assumed to support
        # provider-specific JSON Schema enforcement.  Start with prompt JSON;
        # a connection can explicitly opt into json_object/json_schema.
        "openai_chat": {"structured_output": "prompt_json", "models": True, "stream": False, "usage": True},
        "gemini_openai": {"structured_output": "json_schema", "models": True, "stream": False, "usage": True},
        "sensenova_native": {"structured_output": "prompt_json", "models": True, "stream": False, "usage": True},
        "sensenova_compatible": {"structured_output": "prompt_json", "models": True, "stream": False, "usage": True},
        "ollama": {"structured_output": "prompt_json", "models": True, "stream": False, "usage": False},
    }
    return dict(defaults.get(protocol, {"structured_output": "prompt_json", "models": False, "stream": False, "usage": False}))


def normalize_models(result: Any) -> list[dict[str, Any]]:
    """Normalize native and OpenAI-compatible model-list envelopes.

    SenseNova's native endpoint returns ``data`` as a list and compatibility
    gateways generally use the same shape.  A few proxies use ``models`` or
    nest the list one level deeper, so accept those forms without exposing the
    upstream response wholesale.
    """

    if not isinstance(result, dict):
        return []
    candidates: Any = result.get("data") or result.get("models")
    if isinstance(candidates, dict):
        candidates = candidates.get("data") or candidates.get("models")
    if not isinstance(candidates, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, str):
            model_id = item.strip()
            item_dict: dict[str, Any] = {}
        elif isinstance(item, dict):
            item_dict = item
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
        else:
            continue
        if not model_id:
            continue

        permission = item_dict.get("permission") or item_dict.get("permissions")
        allow_chat = item_dict.get("allow_chat")
        if allow_chat is None and isinstance(permission, list):
            for entry in permission:
                if isinstance(entry, dict) and "allow_chat" in entry:
                    allow_chat = entry.get("allow_chat")
                    break
        if isinstance(allow_chat, str):
            allow_chat = allow_chat.lower() in {"true", "1", "yes"}
        if not isinstance(allow_chat, bool):
            allow_chat = None

        normalized.append({
            "id": model_id,
            "name": str(item_dict.get("name") or model_id),
            "type": item_dict.get("type"),
            "owned_by": item_dict.get("owned_by") or item_dict.get("owner"),
            "allow_chat": allow_chat,
        })
    return normalized


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part for item in value for part in [_first_text(item)] if part)
    if not isinstance(value, dict):
        return ""
    for key in ("output_text", "text"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    choices = value.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                text = _first_text(choice.get("message")) or _first_text(choice.get("delta")) or _first_text(choice.get("text"))
                if text:
                    return text
    for key in ("message", "content", "output", "data", "delta"):
        if key in value:
            text = _first_text(value[key])
            if text:
                return text
    return ""


def _response_container(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else result


def normalize_response(result: Any) -> NormalizedResponse:
    container = _response_container(result)
    choices = container.get("choices") if isinstance(container, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    return NormalizedResponse(
        text=_first_text(result).strip(),
        usage=container.get("usage") if isinstance(container.get("usage"), dict) else None,
        request_id=str(container.get("id") or "") or None,
        finish_reason=str(choice.get("finish_reason") or "") or None,
        raw=result,
    )
