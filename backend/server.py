import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from backend.llm.adapters import (
        SUPPORTED_PROTOCOLS,
        adapter_capabilities,
        get_adapter,
        normalize_models,
        normalize_response,
        protocol_for_config,
    )
    from backend.llm.contracts import LLMRequest
    from backend.llm.errors import classify_http_status
    from backend.credentials import CredentialStorageUnavailable, delete_secret, read_secret, write_secret
except ModuleNotFoundError:  # Running backend/server.py directly from its folder.
    from llm.adapters import (
        SUPPORTED_PROTOCOLS,
        adapter_capabilities,
        get_adapter,
        normalize_models,
        normalize_response,
        protocol_for_config,
    )
    from llm.contracts import LLMRequest
    from llm.errors import classify_http_status
    from credentials import CredentialStorageUnavailable, delete_secret, read_secret, write_secret

API = "https://api.bilibili.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MODEL_PROBE_MAX_OUTPUT_TOKENS = 256
MODEL_PROBE_RETRY_OUTPUT_TOKENS = 1024
ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
IS_FROZEN = bool(getattr(sys, "frozen", False))
DEFAULT_DATA_ROOT = (
    Path(os.getenv("LOCALAPPDATA") or Path.home()) / "WENL Scribe" / "data"
    if IS_FROZEN
    else ROOT / "data"
)
DATA_ROOT = Path(os.getenv("WENL_DATA_DIR") or DEFAULT_DATA_ROOT)
STATIC_DIR = Path(
    os.getenv("WENL_STATIC_DIR")
    or (BUNDLE_ROOT / "static" if IS_FROZEN else ROOT / "desktop-dist")
)
TASK_DIR = DATA_ROOT / "tasks"
TASK_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR = DATA_ROOT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_ROOT / "config.json"
CREDENTIALS_PATH = DATA_ROOT / "credentials.json"
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in (os.getenv("WENL_ALLOWED_ORIGINS") or "http://localhost:3001,http://127.0.0.1:3001").split(",")
    if origin.strip()
}

MODEL_CACHE = {}
MODEL_LOCK = threading.Lock()
TASKS = {}
TASK_LOCK = threading.Lock()
RESULT_CACHE = {}
RESULTS_BY_ID = {}
CANCEL_EVENTS = {}

STAGES = {
    "pending": (2, "任务已创建，正在准备"),
    "parsing": (8, "正在解析视频信息"),
    "checking_subtitles": (15, "正在检查公开字幕"),
    "downloading": (25, "未发现字幕，正在下载音频"),
    "loading_model": (40, "正在加载本地 Whisper 模型"),
    "transcribing": (45, "正在识别语音内容"),
    "cleaning": (80, "正在整理逐字稿"),
    "summarizing": (84, "正在生成内容总结"),
    "validating": (97, "正在校验观点与原文依据"),
    "completed": (100, "处理完成"),
    "partial": (100, "部分完成，已保留可用结果"),
    "failed": (100, "处理失败"),
    "cancelled": (100, "任务已取消"),
}

ERROR_MESSAGES = {
    "VIDEO_URL_INVALID": "视频链接无效",
    "VIDEO_RESTRICTED": "视频可能需要登录、付费或受到地区限制",
    "VIDEO_INFO_FETCH_FAILED": "无法读取视频信息",
    "SUBTITLE_FETCH_FAILED": "无法读取公开视频字幕",
    "AUDIO_DOWNLOAD_FAILED": "音频下载失败",
    "WHISPER_MODEL_LOAD_FAILED": "Whisper 模型加载失败",
    "TRANSCRIPTION_FAILED": "本地语音转录失败",
    "API_KEY_INVALID": "总结服务的 API Key 无效或已过期",
    "API_PERMISSION_DENIED": "总结服务拒绝访问：当前账号没有访问该接口或模型的权限",
    "API_MODEL_NOT_FOUND": "总结模型不存在或不可用",
    "API_INVALID_REQUEST": "总结服务拒绝了请求参数或请求格式",
    "API_CONTEXT_TOO_LARGE": "逐字稿超过总结服务的上下文长度限制",
    "API_CONFLICT": "总结服务暂时无法处理该请求",
    "API_PROVIDER_ERROR": "总结服务返回了供应商错误",
    "API_RATE_LIMITED": "总结服务请求频率超过限制",
    "API_QUOTA_EXCEEDED": "总结服务额度已用完",
    "API_TIMEOUT": "总结服务请求超时",
    "API_SERVICE_UNAVAILABLE": "总结服务暂时不可用",
    "SUMMARY_JSON_INVALID": "总结服务返回的 JSON 无法解析",
    "SUMMARY_FIELD_MISSING": "总结服务返回字段不完整",
    "SUMMARY_EVIDENCE_FAILED": "总结观点没有找到对应原文",
    "TASK_CANCELLED": "任务已由用户取消",
    "TASK_TIMEOUT": "任务长时间没有更新",
    "UNKNOWN": "处理过程中发生未知错误",
}


class TaskError(Exception):
    def __init__(self, code, message=None, stage=None, retryable=True):
        super().__init__(message or ERROR_MESSAGES.get(code, code))
        self.code = code
        self.stage = stage
        self.retryable = retryable


class TaskCancelled(TaskError):
    def __init__(self):
        super().__init__("TASK_CANCELLED", ERROR_MESSAGES["TASK_CANCELLED"], retryable=True)


def now_ms():
    return int(time.time() * 1000)


def task_dir(job_id):
    path = TASK_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if any(word in key.lower() for word in ("key", "token", "authorization", "cookie", "secret")) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
        value = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    return value


def log_task(job_id, event, **fields):
    entry = {"time": now_ms(), "event": event, **redact(fields)}
    path = task_dir(job_id) / "task.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def check_cancel(job_id):
    event = CANCEL_EVENTS.get(job_id)
    if event and event.is_set():
        raise TaskCancelled()


def http_error_payload(exc):
    """Read a provider error body without exposing credentials in diagnostics."""
    cached = getattr(exc, "_wenl_error_payload", None)
    if isinstance(cached, dict):
        return cached
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error", payload)
    result = error if isinstance(error, dict) else {"message": str(error)}
    try:
        exc._wenl_error_payload = result
    except AttributeError:
        pass
    return result


def provider_error_code(details):
    if not isinstance(details, dict):
        return None
    code = details.get("code")
    if code is not None:
        return code
    status = details.get("status")
    if isinstance(status, dict):
        return status.get("code")
    return None


def http_error_message(exc):
    details = http_error_payload(exc)
    provider_code = provider_error_code(details)
    provider_message = str(details.get("message") or "").strip()
    host = str(getattr(exc, "url", "") or "").lower()
    if exc.code == 403 and "sensenova" in host and str(provider_code) == "7":
        return "HTTP 403（商汤错误码 7）：当前账号没有访问该接口或模型的权限；请在商汤控制台订阅中心开通 API/模型，并确认模型 ID。"
    if exc.code == 401:
        return "HTTP 401：API Key/API_TOKEN 无效或已过期，请重新生成并保存。"
    if exc.code == 403:
        return "HTTP 403：服务端拒绝访问，请检查 API Key、账号权限和模型是否已开通。"
    if exc.code == 404:
        return "HTTP 404：接口路径或模型 ID 不存在，请检查 API 地址和模型清单。"
    if provider_message:
        return f"HTTP {exc.code}：{provider_message}"
    return str(exc)


def error_info(exc, stage=None):
    retry_after = None
    if isinstance(exc, TaskError):
        code = exc.code
        stage = exc.stage or stage
        retryable = exc.retryable
    elif isinstance(exc, urllib.error.HTTPError):
        details = http_error_payload(exc)
        classification = classify_http_status(exc.code, provider_error_code(details))
        code = classification.code
        retryable = classification.retryable
        raw_retry_after = getattr(exc, "headers", {}).get("Retry-After") if getattr(exc, "headers", None) else None
        try:
            retry_after = max(0.0, float(raw_retry_after)) if raw_retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
    elif isinstance(exc, (TimeoutError, urllib.error.URLError)):
        code = "API_TIMEOUT" if stage in ("summarizing", "validating") else "UNKNOWN"
        retryable = True
    elif isinstance(exc, json.JSONDecodeError):
        code = "SUMMARY_JSON_INVALID"
        retryable = True
    elif isinstance(exc, ValueError):
        code = "VIDEO_URL_INVALID" if stage in (None, "parsing") else "UNKNOWN"
        retryable = True
    else:
        code = "UNKNOWN"
        retryable = True
    return {
        "code": code,
        "message": http_error_message(exc) if isinstance(exc, urllib.error.HTTPError) else (str(exc) or ERROR_MESSAGES.get(code, code)),
        "stage": stage,
        "retryable": retryable,
        "retry_after": retry_after,
    }


def normalize_segment(item, source="unknown"):
    text = str(item.get("text") or item.get("content") or "").strip()
    start = item.get("start", item.get("from"))
    end = item.get("end", item.get("to"))
    try:
        start = round(float(start), 3) if start is not None else None
    except (TypeError, ValueError):
        start = None
    try:
        end = round(float(end), 3) if end is not None else start
    except (TypeError, ValueError):
        end = start
    return {"start": start, "end": end, "text": text, "source": source}


def segments_text(segments):
    return "\n".join(segment["text"] for segment in segments if segment.get("text"))


def timestamp_text(seconds):
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_segments_for_ai(segments):
    rows = []
    for segment in segments:
        if segment.get("start") is None:
            rows.append(segment["text"])
        else:
            rows.append(f"[{segment['start']:.2f}-{(segment.get('end') or segment['start']):.2f}] {segment['text']}")
    return "\n".join(rows)


def request_json(url, data=None, headers=None, timeout=60):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    merged = {"User-Agent": UA, **(headers or {})}
    if body is not None:
        merged["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=merged)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_bvid(value):
    url_match = re.search(r"https?://[^\s<>]+", value, flags=re.IGNORECASE)
    if not url_match:
        raise ValueError("没有找到有效链接。请粘贴 B 站视频链接或完整分享文案。")
    link = url_match.group(0).rstrip("，,。；;！!？?、】）)]}'\"")
    if "b23.tv" in link:
        req = urllib.request.Request(link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as response:
            link = response.geturl()
    match = re.search(r"(BV[0-9A-Za-z]{10})", link)
    if not match:
        raise ValueError("暂时只支持 B 站公开视频。请确认链接来自 bilibili.com 或 b23.tv。")
    return match.group(1), link


def normalize_page(value):
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, page)


def resolve_page(link):
    raw = (urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("p") or ["1"])[0]
    return normalize_page(raw)


def get_video(link):
    bvid, resolved_link = resolve_bvid(link)
    page = resolve_page(resolved_link)
    view = request_json(f"{API}/x/web-interface/view?bvid={bvid}")
    if view.get("code") != 0:
        raise ValueError("未能读取视频信息。请确认视频存在且可以公开访问。")
    data = view["data"]
    pages = data.get("pages") or []
    if not pages or page > len(pages):
        raise ValueError(f"视频不存在第 {page} 个分P，请检查链接中的 p 参数。")
    selected_page = pages[page - 1]
    source_url = f"https://www.bilibili.com/video/{bvid}?p={page}"
    return {
        "bvid": bvid,
        "page": page,
        "cid": selected_page["cid"],
        "title": data["title"],
        "author": data["owner"]["name"],
        "duration": selected_page.get("duration") or data["duration"],
        "cover": data.get("pic", "").replace("http://", "https://"),
        "source_url": source_url,
    }


def get_subtitles(video):
    endpoint = f"{API}/x/player/v2?bvid={video['bvid']}&cid={video['cid']}"
    payload = request_json(endpoint)
    tracks = ((payload.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    if not tracks:
        return []
    url = tracks[0].get("subtitle_url", "")
    if url.startswith("//"):
        url = "https:" + url
    subtitle = request_json(url)
    return [normalize_segment(item, "public_subtitle") for item in subtitle.get("body", []) if item.get("content")]


def transcribe(job_id, video, model_name, language, progress):
    progress("downloading", "正在准备视频音频", 20)
    play = request_json(f"{API}/x/player/playurl?bvid={video['bvid']}&cid={video['cid']}&qn=64&fnval=16")
    audio = play.get("data", {}).get("dash", {}).get("audio") or []
    if not audio:
        raise TaskError("VIDEO_RESTRICTED", "未能获取视频音频。视频可能需要登录、付费或存在地区限制。", "downloading")
    audio_url = audio[0].get("baseUrl") or audio[0].get("base_url")
    req = urllib.request.Request(audio_url, headers={"User-Agent": UA, "Referer": video["source_url"]})
    with tempfile.NamedTemporaryFile(suffix=".m4s", delete=False) as temp:
        with urllib.request.urlopen(req, timeout=180) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                check_cancel(job_id)
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                temp.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = 20 + int(downloaded / total * 16)
                    progress("downloading", f"正在下载音频 {downloaded / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB", percent, {"bytes_downloaded": downloaded, "bytes_total": total})
        path = temp.name
    try:
        check_cancel(job_id)
        progress("loading_model", None, 40)
        with MODEL_LOCK:
            if model_name not in MODEL_CACHE:
                from faster_whisper import WhisperModel
                MODEL_CACHE[model_name] = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(MODEL_DIR),
                )
            model = MODEL_CACHE[model_name]
        check_cancel(job_id)
        progress("transcribing", "正在识别语音内容", 45)
        detected_language = None if language == "auto" else language
        whisper_segments, info = model.transcribe(path, language=detected_language, vad_filter=True, beam_size=5)
        segments = []
        duration = max(float(video.get("duration") or 0), 1)
        last_saved = 0.0
        for segment in whisper_segments:
            check_cancel(job_id)
            text = segment.text.strip()
            if not text:
                continue
            normalized = normalize_segment({"start": segment.start, "end": segment.end, "text": text}, "whisper")
            segments.append(normalized)
            if segment.end - last_saved >= 4 or segment.end >= duration:
                percent = min(79, 45 + int(segment.end / duration * 34))
                progress("transcribing", f"正在转录 {timestamp_text(segment.end)} / {timestamp_text(duration)}", percent, {"processed_seconds": round(segment.end, 2), "total_seconds": round(duration, 2)})
                last_saved = segment.end
        progress("cleaning", "正在整理带时间戳逐字稿", 80)
        return segments, info.language
    except TaskCancelled:
        raise
    except Exception as exc:
        if isinstance(exc, TaskError):
            raise
        raise TaskError("TRANSCRIPTION_FAILED", str(exc), "transcribing") from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def load_summary_config():
    stored = {}
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
    provider = os.getenv("SUMMARY_PROVIDER") or stored.get("provider") or "openai"
    base_url = os.getenv("SUMMARY_BASE_URL") or os.getenv("OPENAI_BASE_URL") or stored.get("base_url") or "https://api.openai.com/v1"
    model = os.getenv("SUMMARY_MODEL") or os.getenv("OPENAI_MODEL") or stored.get("model") or "gpt-5-mini"
    protocol_value = os.getenv("SUMMARY_PROTOCOL") or stored.get("protocol")
    try:
        protocol = protocol_for_config({"provider": provider, "protocol": protocol_value, "base_url": base_url})
    except ValueError:
        try:
            protocol = protocol_for_config({"provider": provider, "base_url": base_url})
        except ValueError:
            protocol = "openai_responses"
    if provider == "sensenova":
        # The official docs call this value API_TOKEN. Keep the older
        # SENSENOVA_API_KEY name as a backwards-compatible fallback.
        env_key_name = "SENSENOVA_API_TOKEN" if "SENSENOVA_API_TOKEN" in os.environ else "SENSENOVA_API_KEY"
    else:
        env_key_name = "OPENAI_API_KEY"
    stored_protocol = stored.get("protocol")
    if not stored_protocol and stored.get("provider"):
        try:
            stored_protocol = protocol_for_config(stored)
        except ValueError:
            stored_protocol = ""
    same_credential_scope = stored.get("provider") == provider and stored_protocol == protocol
    credential_ref = stored.get("credential_ref") if same_credential_scope else ""
    if not credential_ref:
        credential_ref = f"{provider}:{protocol}"
    # Keep one encrypted credential per provider/protocol.  Switching the
    # visible provider must not make an existing saved key disappear; the
    # target scope may already have a key even when it is not the active one.
    secure_key = read_secret(CREDENTIALS_PATH, credential_ref)
    legacy_key = stored.get("api_key") if same_credential_scope else ""
    api_key = os.getenv(env_key_name) or secure_key or legacy_key or ""
    credential_storage = "environment" if os.getenv(env_key_name) else ("dpapi" if secure_key else ("legacy_plaintext" if legacy_key else "none"))
    configured = bool(base_url and model and (provider == "compatible" or api_key))
    return {
        "provider": provider,
        "protocol": protocol,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "configured": configured,
        "managed_by_env": bool(os.getenv(env_key_name)),
        "managed_by_env_name": env_key_name,
        "capabilities": adapter_capabilities(protocol),
        "credential_ref": credential_ref,
        "credential_storage": credential_storage,
    }


def public_summary_config():
    config = load_summary_config()
    return {
        "provider": config["provider"],
        "protocol": config["protocol"],
        "base_url": config["base_url"],
        "model": config["model"],
        "has_api_key": bool(config["api_key"]),
        "configured": config["configured"],
        "managed_by_env": config["managed_by_env"],
        "managed_by_env_name": config["managed_by_env_name"],
        "key_hint": f"••••{config['api_key'][-4:]}" if config["api_key"] else "",
        "capabilities": config["capabilities"],
        "credential_storage": config["credential_storage"],
    }


def save_summary_config(payload):
    provider = str(payload.get("provider", "openai")).strip()
    if provider not in ("openai", "gemini", "sensenova", "compatible"):
        raise ValueError("不支持的总结服务类型")
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("API 地址必须是完整的 http:// 或 https:// 地址")
    model = str(payload.get("model", "")).strip()
    if not model:
        raise ValueError("请填写模型名称")
    try:
        protocol = protocol_for_config({"provider": provider, "protocol": payload.get("protocol"), "base_url": base_url})
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError("不支持的总结协议")

    stored = {}
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
    stored_protocol = stored.get("protocol")
    if not stored_protocol and stored.get("provider"):
        try:
            stored_protocol = protocol_for_config(stored)
        except ValueError:
            stored_protocol = ""
    same_credential_scope = stored.get("provider") == provider and stored_protocol == protocol
    credential_ref = stored.get("credential_ref") if same_credential_scope else ""
    if not credential_ref:
        credential_ref = f"{provider}:{protocol}"
    secure_key = read_secret(CREDENTIALS_PATH, credential_ref)
    legacy_key = stored.get("api_key", "") if same_credential_scope else ""
    migrated_key = ""
    if stored.get("provider") == provider and stored_protocol and stored_protocol != protocol:
        old_ref = stored.get("credential_ref") or f"{provider}:{stored_protocol}"
        migrated_key = read_secret(CREDENTIALS_PATH, old_ref) or str(stored.get("api_key") or "")
    key = (secure_key or legacy_key or migrated_key) if "api_key" not in payload else str(payload.get("api_key") or "").strip()
    if payload.get("clear_api_key"):
        try:
            delete_secret(CREDENTIALS_PATH, credential_ref)
        except (CredentialStorageUnavailable, OSError):
            pass
        key = ""
    saved = {"provider": provider, "protocol": protocol, "base_url": base_url, "model": model}
    if key and not payload.get("clear_api_key"):
        try:
            write_secret(CREDENTIALS_PATH, credential_ref, key)
            saved["credential_ref"] = credential_ref
        except (CredentialStorageUnavailable, OSError):
            # Keep the old format as a last-resort compatibility path.  The UI
            # can still save on systems where DPAPI is unavailable.
            saved["api_key"] = key
    atomic_write_json(CONFIG_PATH, saved)
    return public_summary_config()


def summary_prompt(title, transcript):
    return f"""请基于下面的逐字稿生成忠实、克制的视频总结。
只总结说话者明确表达的内容，不使用外部知识，不补充事实，不把猜测改写成定论。
区分“视频作者的判断”和“已确认的客观事实”；有歧义时保留限定词。
summary 用 60 至 120 字概括主旨，且只能综合 key_points 中已被原句支持的观点；
key_points 给出 3 至 6 项，每项包含 claim、evidence 和 kind；
evidence 必须逐字复制逐字稿正文、禁止改写，也不要包含方括号中的时间戳；
kind 只能是：作者观点、嘉宾观点、事实陈述、案例、推测、引用；
outline 按视频实际论述顺序给出 2 至 5 段。
若转写质量不足，应减少结论数量，不要猜测。

标题：{title}
逐字稿：
{transcript}"""


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                    "kind": {"type": "string", "enum": ["作者观点", "嘉宾观点", "事实陈述", "案例", "推测", "引用"]},
                },
                "required": ["claim", "evidence", "kind"],
                "additionalProperties": False,
            },
        },
        "outline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                "required": ["title", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "key_points", "outline"],
    "additionalProperties": False,
}


def response_text(result):
    """Backward-compatible wrapper around the protocol response normalizer."""
    return normalize_response(result).text


def summary_chat_endpoint(config):
    """Backward-compatible endpoint helper for older callers and tests."""
    adapter = get_adapter(config)
    request = LLMRequest(model=str(config.get("model") or ""), prompt="")
    prepared = adapter.prepare(config, request)
    return prepared.endpoint, prepared.protocol == "sensenova_native"


def request_summary(config, title, transcript):
    prompt = summary_prompt(title, transcript) + "\n\n请按 summary、key_points、outline 三个字段输出 JSON；key_points 的每项都必须包含 claim、evidence 与 kind。"
    adapter = get_adapter(config)
    prepared = adapter.prepare(
        config,
        LLMRequest(
            model=config["model"],
            prompt=prompt,
            schema=SUMMARY_SCHEMA,
            schema_name="video_summary",
            response_mode=str(config.get("response_mode") or "auto"),
            max_output_tokens=4096,
            timeout=240,
        ),
    )
    result = request_json(prepared.endpoint, prepared.payload, prepared.headers, prepared.timeout)
    normalized = adapter.parse(result)
    text = normalized.text
    if not text:
        raise TaskError("SUMMARY_FIELD_MISSING", "总结服务没有返回文本", "summarizing")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise TaskError("SUMMARY_JSON_INVALID", "总结服务返回的 JSON 无法解析", "summarizing") from exc


def request_summary_with_retry(config, title, transcript, attempts=3, on_retry=None):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return request_summary(config, title, transcript)
        except Exception as exc:
            last_error = exc
            info = error_info(exc, "summarizing")
            if not info["retryable"] or attempt == attempts:
                raise
            if on_retry:
                on_retry(attempt, info)
            delay = info.get("retry_after") or min(2 ** (attempt - 1), 4)
            time.sleep(min(max(float(delay), 0.0), 30.0))
    raise last_error


def compact_text(value):
    return re.sub(r"\s+", "", str(value or ""))


def locate_evidence(quote, segments):
    needle = compact_text(quote)
    if len(needle) < 6:
        return None
    compact_segments = [compact_text(segment.get("text")) for segment in segments]
    transcript = "".join(compact_segments)
    evidence_offset = transcript.find(needle)
    if evidence_offset < 0:
        return None

    cursor = 0
    start_index = None
    start = None
    end_index = None
    end = None
    evidence_end = evidence_offset + len(needle)
    for index, (segment, text) in enumerate(zip(segments, compact_segments)):
        segment_end_offset = cursor + len(text)
        if start_index is None and evidence_offset < segment_end_offset:
            start_index = index
            start = segment.get("start")
            segment_end = segment.get("end")
            if start is not None and segment_end is not None and segment_end > start and text:
                progress = max(0.0, min(1.0, (evidence_offset - cursor) / len(text)))
                start = round(start + (segment_end - start) * progress, 3)
        if start_index is not None and evidence_end <= segment_end_offset:
            end_index = index
            end = segment.get("end")
            break
        cursor = segment_end_offset

    if start_index is not None:
        end_index = end_index if end_index is not None else len(segments) - 1
        end = end if end is not None else segments[end_index].get("end")
        context_start = max(0, start_index - 1)
        context_end = min(len(segments), end_index + 2)
        return {
            "start": start,
            "end": end,
            "context": " ".join(item["text"] for item in segments[context_start:context_end]),
            "segment_start": start_index,
            "segment_end": end_index,
        }
    return None


def validate_ai_summary(summary, segments):
    if not isinstance(summary, dict) or not isinstance(summary.get("summary"), str):
        raise TaskError("SUMMARY_FIELD_MISSING", "总结服务返回格式不完整", "validating")
    claims = []
    seen_claims = set()
    for item in summary.get("key_points", []):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        quote = str(item.get("evidence", "")).strip()
        kind = str(item.get("kind") or "作者观点").strip()
        location = locate_evidence(quote, segments)
        signature = compact_text(claim)
        if claim and quote and location and signature not in seen_claims:
            claims.append({
                "claim": claim,
                "evidence": quote,
                "kind": kind if kind in ("作者观点", "嘉宾观点", "事实陈述", "案例", "推测", "引用") else "作者观点",
                "start": location["start"],
                "end": location["end"],
                "context": location["context"],
                "verified": True,
            })
            seen_claims.add(signature)
        if len(claims) == 6:
            break
    outline = [item for item in summary.get("outline", []) if isinstance(item, dict) and item.get("title") and item.get("content")][:5]
    if not claims:
        raise TaskError("SUMMARY_EVIDENCE_FAILED", "AI 返回的核心观点没有找到对应原文，已拒绝保存这次总结", "validating")
    return {
        "summary": summary["summary"].strip(),
        "claims": claims,
        "key_points": [item["claim"] for item in claims],
        "outline": outline,
        "evidence": [item["evidence"] for item in claims],
        "summary_type": "generative",
    }


def transcript_chunks(segments, max_chunks=8):
    total_chars = sum(len(segment.get("text", "")) for segment in segments)
    if total_chars <= 24000:
        return [segments]
    target = max(16000, (total_chars + max_chunks - 1) // max_chunks)
    chunks = []
    current = []
    length = 0
    for segment in segments:
        current.append(segment)
        length += len(segment.get("text", ""))
        if length >= target:
            chunks.append(current)
            current = []
            length = 0
    if current:
        chunks.append(current)
    return chunks


def ai_summary(title, segments, progress=None, job_id=None):
    config = load_summary_config()
    if not config["configured"]:
        return None
    chunks = transcript_chunks(segments)
    if len(chunks) == 1:
        if job_id:
            check_cancel(job_id)
        raw = request_summary_with_retry(config, title, format_segments_for_ai(segments))
        if progress:
            progress("validating", "正在校验观点与原文依据", 97)
        return validate_ai_summary(raw, segments)

    verified_sections = []
    failed_sections = []
    for index, chunk_segments in enumerate(chunks, 1):
        if job_id:
            check_cancel(job_id)
        if progress:
            percent = 84 + int((index - 1) / max(len(chunks), 1) * 11)
            progress("summarizing", f"正在总结第 {index} / {len(chunks)} 段", percent, {"summary_chunk": index, "summary_chunks": len(chunks)})
        try:
            section = validate_ai_summary(
                request_summary_with_retry(
                    config,
                    f"{title}（第 {index}/{len(chunks)} 段）",
                    format_segments_for_ai(chunk_segments),
                    on_retry=lambda attempt, info: log_task(job_id, "summary_retry", chunk=index, attempt=attempt, error=info) if job_id else None,
                ),
                chunk_segments,
            )
        except Exception as exc:
            failed_sections.append({"index": index, "error": error_info(exc, "summarizing")})
            if job_id:
                log_task(job_id, "summary_chunk_failed", chunk=index, error=failed_sections[-1]["error"])
            continue
        lines = [f"第 {index} 段摘要：{section['summary']}"]
        for claim in section["claims"]:
            lines.append(f"- 观点：{claim['claim']}\n  原文：{claim['evidence']}\n  类型：{claim['kind']}")
        verified_sections.append({"text": "\n".join(lines), "section": section})
    if not verified_sections:
        raise TaskError("SUMMARY_EVIDENCE_FAILED", "所有总结分段均未通过校验", "validating")

    if job_id:
        check_cancel(job_id)
    if progress:
        progress("validating", f"正在汇总 {len(verified_sections)} 个有效分段", 97, {"validated_chunks": len(verified_sections), "failed_chunks": len(failed_sections)})
    digest = "\n\n".join(item["text"] for item in verified_sections)
    try:
        final = request_summary_with_retry(config, title, digest)
        result = validate_ai_summary(final, segments)
    except Exception:
        claims = []
        for item in verified_sections:
            claims.extend(item["section"]["claims"])
        claims = claims[:6]
        result = {
            "summary": "；".join(item["section"]["summary"] for item in verified_sections[:3])[:220],
            "claims": claims,
            "key_points": [item["claim"] for item in claims],
            "outline": [],
            "evidence": [item["evidence"] for item in claims],
            "summary_type": "generative",
        }
        failed_sections.append({"index": "final", "error": {"code": "SUMMARY_JSON_INVALID", "message": "最终汇总失败，已保留分段结果", "stage": "validating", "retryable": True}})
    result["summary_stats"] = {"total": len(chunks), "completed": len(verified_sections), "failed": len(failed_sections), "failures": failed_sections}
    return result


def probe_summary_service(config, max_output_tokens=MODEL_PROBE_MAX_OUTPUT_TOKENS, allow_retry=True):
    probe_prompt = '这是一次 API 连通性测试。请只返回一个 JSON 对象：{"ok":true}，不要输出 Markdown 或解释。'
    adapter = get_adapter(config)
    prepared = adapter.prepare(
        config,
        LLMRequest(
            model=config["model"],
            prompt=probe_prompt,
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            schema_name="connection_probe",
            response_mode=str(config.get("response_mode") or "auto"),
            max_output_tokens=max_output_tokens,
            timeout=60,
        ),
    )
    result = request_json(prepared.endpoint, prepared.payload, prepared.headers, prepared.timeout)
    normalized = adapter.parse(result)
    if not normalized.text:
        if normalized.finish_reason == "length":
            if allow_retry and max_output_tokens < MODEL_PROBE_RETRY_OUTPUT_TOKENS:
                return probe_summary_service(
                    config,
                    max_output_tokens=MODEL_PROBE_RETRY_OUTPUT_TOKENS,
                    allow_retry=False,
                )
            message = f"模型在输出最终内容前达到 {max_output_tokens} Token 上限，请提高输出上限或关闭推理模式"
        else:
            message = "总结服务返回为空"
        raise TaskError("API_PROVIDER_ERROR", message, "testing", retryable=False)
    return normalized


def test_summary_service():
    config = load_summary_config()
    if not config["configured"]:
        raise ValueError("请先填写并保存可用的 API 配置")
    normalized = probe_summary_service(config)
    return {
        "ok": True,
        "message": f"连接成功：{config['model']}",
        "protocol": config["protocol"],
        "request_id": normalized.request_id,
    }


def probe_failure_message(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return http_error_message(exc)
    return str(exc).strip() or exc.__class__.__name__


def list_summary_models(selection_mode="auto"):
    """Read the models visible to the configured account and select one.

    This mirrors the standalone SenseNova tester: authenticate the model-list
    request with the saved key, then use the provider's returned IDs instead
    of asking the user to guess a model name.
    """

    selection_mode = str(selection_mode or "auto").strip().lower()
    if selection_mode not in ("auto", "manual"):
        raise ValueError("不支持的模型选择模式")

    config = load_summary_config()
    if not config["configured"]:
        raise ValueError("璇峰厛濉啓骞朵繚瀛樺彲鐢ㄧ殑 API Key")
    adapter = get_adapter(config)
    if not adapter.capabilities(config).get("models"):
        raise ValueError("褰撳墠鎺ュ彛鍗忚涓嶆敮鎸佽姹傛ā鍨嬫竻鍗�")

    original_config = config
    attempts = [config]
    if config["provider"] == "sensenova":
        # Existing installations may still point at the native endpoint while
        # the tester and current compatibility docs use an OpenAI-compatible
        # gateway. Try both supported gateways with the same saved key.
        for base_url in (
            "https://api.sensenova.cn/compatible-mode/v2",
            "https://token.sensenova.cn/v1",
        ):
            candidate = {**config, "protocol": "sensenova_compatible", "base_url": base_url}
            if not any(item["protocol"] == candidate["protocol"] and item["base_url"] == candidate["base_url"] for item in attempts):
                attempts.append(candidate)

    models = []
    last_http_error = None
    for candidate in attempts:
        candidate_adapter = get_adapter(candidate)
        if not candidate_adapter.capabilities(candidate).get("models"):
            continue
        try:
            candidate_result = request_json(
                candidate_adapter.models_endpoint(candidate),
                headers=candidate_adapter.models_headers(candidate),
                timeout=60,
            )
        except urllib.error.HTTPError as exc:
            last_http_error = exc
            if candidate["provider"] != "sensenova" or exc.code not in (403, 404):
                raise
            continue
        candidate_models = normalize_models(candidate_result)
        if candidate_models:
            config = candidate
            models = candidate_models
            break

    if not models and last_http_error:
        raise last_http_error
    if not models:
        raise TaskError("API_MODEL_LIST_EMPTY", "API 鏈繑鍥炲彲鐢ㄦā鍨嬫竻鍗�", "testing", retryable=False)

    chat_models = [item for item in models if item.get("allow_chat") is not False]
    candidates = chat_models or models
    preferred_model = config["model"]
    selected = next((item for item in candidates if item["id"] == preferred_model), candidates[0])
    selected_model = selected["id"]
    selection_failures = []

    if config["provider"] == "sensenova":
        if selection_mode == "manual":
            try:
                probe_summary_service({**config, "model": preferred_model})
            except Exception as exc:
                raise TaskError(
                    "API_PROVIDER_ERROR",
                    f"模型 {preferred_model} 验证失败：{probe_failure_message(exc)}",
                    "testing",
                    retryable=False,
                ) from exc
            selected_model = preferred_model
        else:
            # SenseNova's model list may omit chat permissions.  Automatic
            # discovery may probe several models, but manual selection must
            # never be silently replaced by a fallback model.
            probe_candidates = [selected] + [item for item in candidates if item["id"] != selected["id"]]
            usable_model = None
            for candidate_model in probe_candidates[:8]:
                try:
                    probe_summary_service({**config, "model": candidate_model["id"]})
                except Exception as exc:
                    selection_failures.append({
                        "model": candidate_model["id"],
                        "reason": probe_failure_message(exc)[:240],
                    })
                    continue
                usable_model = candidate_model
                break
            if usable_model is None:
                raise TaskError("API_MODEL_NOT_FOUND", "模型列表中没有可用的对话模型，请在高级设置中手动填写模型 ID", "testing", retryable=False)
            selected_model = usable_model["id"]

    # Persist the provider-selected model so the next task needs no manual
    # model entry.  The existing credential reference is preserved by the
    # normal config-saving path.
    config_changed = config["protocol"] != original_config["protocol"] or config["base_url"] != original_config["base_url"]
    if config_changed or selected_model != config["model"]:
        save_payload = {
            "provider": config["provider"],
            "protocol": config["protocol"],
            "base_url": config["base_url"],
            "model": selected_model,
        }
        if config_changed:
            save_payload["api_key"] = config["api_key"]
        save_summary_config(save_payload)

    selection = {
        "mode": selection_mode,
        "requested_model": preferred_model,
        "selected_model": selected_model,
    }
    if selection_failures:
        selection["failures"] = selection_failures

    return {
        "ok": True,
        "models": models,
        "selected_model": selected_model,
        "selection": selection,
        "config": public_summary_config(),
    }


def clean_sentence(sentence):
    sentence = re.sub(r"\s+", "", sentence).strip(" ，,。；;")
    return sentence + ("。" if sentence and sentence[-1] not in "。！？!?" else "")


def sentence_score(sentence, frequencies, index, total):
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", sentence)
    grams = [clean[i:i + 2] for i in range(max(0, len(clean) - 1))]
    density = sum(min(frequencies[g], 7) for g in grams) / max(len(grams), 1)
    cues = {
        "核心": 5, "意味着": 5, "本质": 6, "建议": 6, "结论": 6, "关键": 4,
        "未来": 3, "影响": 3, "必须": 4, "转向": 4, "机会": 3, "一是": 5,
        "二是": 5, "才是": 5, "不是": 2, "而是": 4, "因此": 4, "总之": 6,
    }
    cue_score = sum(weight for cue, weight in cues.items() if cue in sentence)
    conclusion_bonus = 2 if index >= total * .72 else 0
    length_penalty = 3 if len(sentence) < 22 or len(sentence) > 150 else 0
    return density + cue_score + conclusion_bonus - length_penalty


def choose_diverse(ranked, count):
    selected = []
    for candidate in ranked:
        chars = set(candidate[2])
        if all(len(chars & set(old[2])) / max(len(chars | set(old[2])), 1) < .52 for old in selected):
            selected.append(candidate)
        if len(selected) == count:
            break
    return selected


def split_transcript(transcript):
    markers = r"(?=(?:可如今|而本轮|过去\d*年|未来|往后|当下|一是|二是|有人|旧时代|新时代|给年轻|看清趋势|最后|总之|因此))"
    sentences = []
    for block in re.split(r"[。！？!?\n]+", transcript):
        block = block.strip()
        if not block:
            continue
        pieces = [piece.strip() for piece in re.sub(markers, "\n", block).splitlines() if piece.strip()]
        for piece in pieces:
            if len(piece) > 105:
                for start in range(0, len(piece), 90):
                    chunk = piece[start:start + 90]
                    if len(chunk) >= 16:
                        sentences.append(clean_sentence(chunk))
            elif len(piece) >= 16:
                sentences.append(clean_sentence(piece))
    return sentences


def local_summary(title, transcript, segments=None):
    segments = segments or [{"start": None, "end": None, "text": line, "source": "legacy"} for line in transcript.splitlines() if line.strip()]
    sentences = split_transcript(transcript)
    incomplete_starts = ("才是", "以及", "并且", "而且")
    incomplete_ends = ("在为。", "正是把。", "从。", "对。", "和。", "与。", "的。")
    complete_sentences = [s for s in sentences if not s.startswith(incomplete_starts) and not s.endswith(incomplete_ends)]
    if complete_sentences:
        sentences = complete_sentences
    if not sentences:
        fallback = clean_sentence(transcript[:220])
        location = locate_evidence(fallback.rstrip("。"), segments) or {}
        claim = {"claim": fallback, "evidence": fallback, "kind": "原文摘录", "start": location.get("start"), "end": location.get("end"), "context": location.get("context", fallback), "verified": bool(location)}
        return {"summary": fallback, "claims": [claim], "key_points": [fallback], "outline": [], "evidence": [fallback], "summary_type": "extractive"}

    clean_text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", transcript)
    frequencies = Counter(clean_text[i:i + 2] for i in range(max(0, len(clean_text) - 1)))
    ranked = sorted(
        ((sentence_score(sentence, frequencies, i, len(sentences)), i, sentence) for i, sentence in enumerate(sentences)),
        reverse=True,
    )
    selected = choose_diverse(ranked, min(5, len(sentences)))
    key_points = [item[2][:140] for item in sorted(selected, key=lambda item: item[1])]

    conclusion_candidates = [item for item in ranked if any(cue in item[2] for cue in ("本质", "结论", "因此", "总之", "才是", "建议", "未来"))]
    best = (conclusion_candidates or ranked)[0][2]
    summary = best[:180]

    outline = []
    section_count = min(3, len(sentences))
    for section in range(section_count):
        start = round(len(sentences) * section / section_count)
        end = round(len(sentences) * (section + 1) / section_count)
        candidates = [item for item in ranked if start <= item[1] < end]
        if not candidates:
            continue
        sentence = candidates[0][2][:120]
        labels = ("问题与背景", "核心论述", "结论与建议")
        outline.append({"title": labels[section], "content": sentence})

    claims = []
    for point in key_points:
        quote = point.rstrip("。")
        location = locate_evidence(quote, segments) or {}
        claims.append({"claim": point, "evidence": point, "kind": "原文摘录", "start": location.get("start"), "end": location.get("end"), "context": location.get("context", point), "verified": bool(location)})

    return {
        "summary": summary,
        "claims": claims,
        "key_points": key_points,
        "outline": outline,
        "evidence": key_points[:3],
        "summary_type": "extractive",
    }


def set_stage(job_id, stage, detail=None, progress=None, progress_detail=None):
    default_progress, default_message = STAGES[stage]
    with TASK_LOCK:
        task = TASKS[job_id]
        previous = task.get("stage")
        status = stage if stage in ("completed", "partial", "failed", "cancelled") else ("pending" if stage == "pending" else "processing")
        task.update({
            "status": status,
            "stage": stage,
            "progress": default_progress if progress is None else max(0, min(100, int(progress))),
            "message": detail or default_message,
            "updated_at": now_ms(),
        })
        if progress_detail is not None:
            task["progress_detail"] = progress_detail
        if stage in ("completed", "partial", "failed", "cancelled"):
            task["completed_at"] = now_ms()
        save_task(task)
    if previous != stage:
        log_task(job_id, "stage_changed", stage=stage, message=detail or default_message)


def task_metadata(task):
    keys = ("job_id", "input", "model", "summary_mode", "summary_provider", "summary_protocol", "summary_model", "language", "title", "author", "duration", "cover", "source_url", "bvid", "page", "cid", "created_at", "method_base", "detected_language")
    return {key: task.get(key) for key in keys if task.get(key) is not None}


def task_status(task):
    keys = ("job_id", "status", "stage", "progress", "message", "created_at", "updated_at", "started_at", "completed_at", "error", "error_info", "warning", "available_results", "progress_detail", "summary_stats")
    return {key: task.get(key) for key in keys if task.get(key) is not None}


def save_task(task):
    directory = task_dir(task["job_id"])
    atomic_write_json(directory / "metadata.json", task_metadata(task))
    atomic_write_json(directory / "status.json", task_status(task))
    segments = task.get("transcript_segments") or ((task.get("result") or {}).get("segments"))
    if segments:
        atomic_write_json(directory / "transcript.json", {"version": 1, "segments": segments, "text": segments_text(segments)})
    result = task.get("result")
    if result:
        atomic_write_text(directory / "transcript.md", transcript_markdown(result))
        if result.get("summary"):
            summary_data = {key: value for key, value in result.items() if key not in ("transcript", "segments")}
            atomic_write_json(directory / "summary.json", summary_data)
            atomic_write_text(directory / "summary.md", summary_markdown(result))


def make_base_result(task, video, segments, method):
    return {
        **video,
        "video": {
            "platform": "bilibili",
            "bvid": video.get("bvid"),
            "page": normalize_page(video.get("page")),
            "sourceUrl": video.get("source_url"),
            "title": video.get("title"),
            "author": video.get("author"),
            "duration": video.get("duration"),
        },
        "method": method,
        "transcript": segments_text(segments),
        "segments": segments,
        "job_id": task["job_id"],
    }


def run_job(job_id, resume="auto"):
    task = TASKS[job_id]
    task["started_at"] = now_ms()
    task.pop("error", None)
    task.pop("error_info", None)
    task.pop("warning", None)
    log_task(job_id, "task_started", resume=resume, model=task.get("model"), summary_mode=task.get("summary_mode"))
    try:
        check_cancel(job_id)
        segments = task.get("transcript_segments") if resume == "summary" else None
        video = None
        method = task.get("method_base")
        if segments:
            video = {key: task.get(key) for key in ("bvid", "page", "cid", "title", "author", "duration", "cover", "source_url")}
            if not video.get("title"):
                raise TaskError("VIDEO_INFO_FETCH_FAILED", "历史任务缺少视频信息，无法重新总结", "parsing")
        else:
            set_stage(job_id, "parsing")
            try:
                video = get_video(task["input"])
            except ValueError as exc:
                raise TaskError("VIDEO_URL_INVALID", str(exc), "parsing") from exc
            except Exception as exc:
                raise TaskError("VIDEO_INFO_FETCH_FAILED", str(exc), "parsing") from exc
            with TASK_LOCK:
                task.update(video)
                save_task(task)
            check_cancel(job_id)
            set_stage(job_id, "checking_subtitles")
            try:
                segments = get_subtitles(video)
            except Exception as exc:
                log_task(job_id, "subtitle_fetch_failed", error=error_info(exc, "checking_subtitles"))
                segments = []
            method = "公开字幕"
            detected_language = task["language"]
            if not segments:
                segments, detected_language = transcribe(
                    job_id,
                    video,
                    task["model"],
                    task["language"],
                    lambda stage, detail=None, progress=None, progress_detail=None: set_stage(job_id, stage, detail, progress, progress_detail),
                )
                method = f"本地语音转写 · {task['model']} · {detected_language}"
            else:
                set_stage(job_id, "cleaning", f"已找到 {len(segments)} 条公开字幕，正在整理时间戳", 80, {"segments": len(segments)})
            if not segments:
                raise TaskError("TRANSCRIPTION_FAILED", "没有生成可用的逐字稿", "transcribing")
            with TASK_LOCK:
                task["transcript_segments"] = segments
                task["method_base"] = method
                task["detected_language"] = detected_language
                task["available_results"] = ["transcript"]
                task["result"] = make_base_result(task, video, segments, method)
                RESULTS_BY_ID[job_id] = task["result"]
                save_task(task)
            log_task(job_id, "transcript_saved", segments=len(segments), characters=len(segments_text(segments)), method=method)

        check_cancel(job_id)
        transcript = segments_text(segments)
        set_stage(job_id, "summarizing", "逐字稿已保存，正在生成总结", 84, {"segments": len(segments)})
        summary = None
        summary_error = None
        config = load_summary_config()
        should_use_api = task["summary_mode"] != "local" and config["configured"]
        summary_service = {
            "provider": config["provider"],
            "protocol": config["protocol"],
            "model": config["model"],
        } if should_use_api else {"provider": "local", "protocol": "local", "model": None}
        task.update({
            "summary_provider": summary_service["provider"],
            "summary_protocol": summary_service["protocol"],
            "summary_model": summary_service["model"],
        })
        save_task(task)
        if task["summary_mode"] == "cloud" and not config["configured"]:
            summary_error = {"code": "API_KEY_INVALID", "message": "尚未配置可用的总结 API", "stage": "summarizing", "retryable": True}
        elif should_use_api:
            try:
                summary = ai_summary(
                    video["title"],
                    segments,
                    lambda stage, detail=None, progress=None, progress_detail=None: set_stage(job_id, stage, detail, progress, progress_detail),
                    job_id,
                )
            except TaskCancelled:
                raise
            except Exception as exc:
                summary_error = error_info(exc, "summarizing")
                log_task(job_id, "summary_failed", error=summary_error, traceback=traceback.format_exc())

        if summary:
            suffix = "AI 语义总结"
        else:
            summary = local_summary(video["title"], transcript, segments)
            suffix = "本地原文提要"
        result = {**make_base_result(task, video, segments, method), **summary, "method": f"{method} + {suffix}", "summary_service": summary_service}
        if summary_error:
            result["summary_error"] = summary_error
        summary_stats = summary.get("summary_stats") or {"total": 1, "completed": 1 if not summary_error else 0, "failed": 1 if summary_error else 0}
        is_partial = bool(summary_error or summary_stats.get("failed"))
        with TASK_LOCK:
            task["result"] = result
            task["summary_stats"] = summary_stats
            task["available_results"] = ["transcript", "summary"]
            if summary_error:
                task["warning"] = summary_error
            RESULTS_BY_ID[job_id] = result
            RESULT_CACHE[task.get("input", job_id)] = result
            save_task(task)
        set_stage(job_id, "partial" if is_partial else "completed", summary_error["message"] if summary_error else None)
        log_task(job_id, "task_finished", status="partial" if is_partial else "completed", summary_stats=summary_stats)
    except TaskCancelled as exc:
        with TASK_LOCK:
            task["error_info"] = error_info(exc, task.get("stage"))
            task["error"] = str(exc)
            if task.get("transcript_segments"):
                task["available_results"] = ["transcript"]
            save_task(task)
        set_stage(job_id, "cancelled")
        log_task(job_id, "task_cancelled", stage=task.get("stage"))
    except Exception as exc:
        info = error_info(exc, task.get("stage"))
        log_task(job_id, "task_failed", error=info, traceback=traceback.format_exc())
        with TASK_LOCK:
            task["error_info"] = info
            task["error"] = info["message"]
            has_transcript = bool(task.get("transcript_segments"))
            if has_transcript:
                segments = task["transcript_segments"]
                video = {key: task.get(key) for key in ("bvid", "page", "cid", "title", "author", "duration", "cover", "source_url")}
                summary = local_summary(task.get("title", ""), segments_text(segments), segments)
                task["result"] = {**make_base_result(task, video, segments, task.get("method_base", "转录")), **summary, "method": f"{task.get('method_base', '转录')} + 本地原文提要", "summary_error": info}
                task["available_results"] = ["transcript", "summary"]
                RESULTS_BY_ID[job_id] = task["result"]
            save_task(task)
        set_stage(job_id, "partial" if task.get("transcript_segments") else "failed", info["message"])


def create_job(link, model="small", summary_mode="auto", language="auto"):
    if model not in ("small", "medium", "large-v3-turbo"):
        model = "small"
    if summary_mode not in ("auto", "local", "cloud"):
        summary_mode = "auto"
    if language not in ("auto", "zh", "en"):
        language = "auto"
    job_id = uuid.uuid4().hex
    task = {
        "job_id": job_id, "input": link, "status": "pending", "stage": "pending",
        "progress": STAGES["pending"][0], "message": STAGES["pending"][1],
        "model": model, "summary_mode": summary_mode, "language": language,
        "created_at": now_ms(), "updated_at": now_ms(),
    }
    with TASK_LOCK:
        TASKS[job_id] = task
        CANCEL_EVENTS[job_id] = threading.Event()
        save_task(task)
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
    return public_task(task)


def public_task(task, include_result=True):
    if not task:
        return None
    hidden = {"input", "transcript_segments", "method_base"} if include_result else {"input", "transcript_segments", "method_base", "result"}
    return {key: value for key, value in task.items() if key not in hidden}


def legacy_segments(result):
    transcript = result.get("transcript", "")
    lines = [line.strip() for line in transcript.splitlines() if line.strip()] or ([transcript] if transcript else [])
    return [{"start": None, "end": None, "text": line, "source": "legacy"} for line in lines]


def ensure_result_structure(result, segments):
    if not result:
        return None
    result["segments"] = segments
    result["transcript"] = segments_text(segments)
    page = normalize_page(result.get("page") or ((result.get("video") or {}).get("page")))
    result["page"] = page
    if result.get("bvid") and not result.get("video"):
        result["video"] = {
            "platform": "bilibili",
            "bvid": result["bvid"],
            "page": page,
            "sourceUrl": result.get("source_url"),
            "title": result.get("title"),
            "author": result.get("author"),
            "duration": result.get("duration"),
        }
    if not result.get("summary_type"):
        result["summary_type"] = "extractive" if "本地" in result.get("method", "") or result.get("method") == "兼容接口" else "generative"
    if not result.get("claims"):
        points = result.get("key_points") or []
        evidence = result.get("evidence") or points
        claims = []
        for index, point in enumerate(points):
            quote = evidence[index] if index < len(evidence) else point
            location = locate_evidence(quote, segments) or {}
            claims.append({"claim": point, "evidence": quote, "kind": "原文摘录" if result["summary_type"] == "extractive" else "作者观点", "start": location.get("start"), "end": location.get("end"), "context": location.get("context", quote), "verified": bool(location)})
        result["claims"] = claims
    return result


def load_task_directory(directory):
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    task = {**metadata, **status}
    transcript_path = directory / "transcript.json"
    segments = []
    if transcript_path.exists():
        segments = json.loads(transcript_path.read_text(encoding="utf-8")).get("segments") or []
        task["transcript_segments"] = segments
    summary_path = directory / "summary.json"
    if summary_path.exists():
        result = json.loads(summary_path.read_text(encoding="utf-8"))
        task["result"] = ensure_result_structure(result, segments or legacy_segments(result))
    return task


def load_tasks():
    for directory in TASK_DIR.iterdir():
        if not directory.is_dir() or not (directory / "metadata.json").exists() or not (directory / "status.json").exists():
            continue
        try:
            task = load_task_directory(directory)
            TASKS[task["job_id"]] = task
        except Exception:
            continue
    for path in TASK_DIR.glob("*.json"):
        try:
            legacy = json.loads(path.read_text(encoding="utf-8"))
            if legacy.get("job_id") in TASKS:
                continue
            result = legacy.get("result")
            segments = legacy_segments(result or {})
            if result:
                legacy["result"] = ensure_result_structure(result, segments)
                legacy["transcript_segments"] = segments
                legacy["available_results"] = ["transcript", "summary"]
                legacy["method_base"] = result.get("method", "转录").split(" + ")[0]
                for key in ("bvid", "page", "cid", "title", "author", "duration", "cover", "source_url"):
                    if result.get(key) is not None:
                        legacy[key] = result[key]
            status_map = {"queued": "pending", "complete": "completed"}
            legacy["status"] = status_map.get(legacy.get("status"), legacy.get("status", "failed"))
            legacy["stage"] = status_map.get(legacy.get("stage"), legacy.get("stage", legacy["status"]))
            if legacy["status"] == "processing":
                legacy.update({"status": "failed", "stage": "failed", "progress": 100, "message": "上次运行被中断，可从已保存阶段重试", "error": "任务在服务关闭时被中断", "error_info": {"code": "TASK_TIMEOUT", "message": "任务在服务关闭时被中断", "stage": legacy.get("stage"), "retryable": True}})
            TASKS[legacy["job_id"]] = legacy
            save_task(legacy)
        except Exception:
            continue
    for job_id, task in TASKS.items():
        CANCEL_EVENTS[job_id] = threading.Event()
        result = task.get("result")
        if result:
            RESULTS_BY_ID[job_id] = result
        if task.get("status") == "processing":
            task.update({"status": "failed", "stage": "failed", "progress": 100, "message": "上次运行被中断，可点击重试", "error": "任务在服务关闭时被中断", "error_info": {"code": "TASK_TIMEOUT", "message": "任务在服务关闭时被中断", "stage": task.get("stage"), "retryable": True}})
            save_task(task)


def transcript_markdown(result):
    segments = result.get("segments") or []
    if segments:
        transcript_blocks = []
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start = segment.get("start")
            if start is None:
                transcript_blocks.append(text)
            else:
                time_link = video_time_link(result.get("source_url", ""), start)
                transcript_blocks.append(f"**[{timestamp_text(start)}]({time_link})**  \n{text}")
        transcript = "\n\n".join(transcript_blocks)
    else:
        transcript = result.get("transcript", "")
    return "\n".join([
        f"# {result['title']}",
        "",
        "> **逐字稿 · 留文**",
        "",
        "---",
        "",
        "## 视频信息",
        "",
        "| 项目 | 内容 |",
        "| :--- | :--- |",
        f"| 视频 | [{markdown_table_cell(result['title'])}]({result['source_url']}) |",
        f"| 作者 | {markdown_table_cell(result.get('author', '未知'))} |",
        f"| 时长 | {timestamp_text(result.get('duration'))} |",
        f"| 转录方式 | {markdown_table_cell(result.get('method', '未知'))} |",
        "",
        "## 阅读说明",
        "",
        "- 点击时间戳可以回到原视频对应位置。",
        "- 逐字稿按语音识别片段分段，保留原始表达顺序。",
        "- 人名、数字和专有名词可能存在识别误差，重要内容请结合原视频核对。",
        "",
        "---",
        "",
        "## 完整逐字稿",
        "",
        transcript,
        "",
        "---",
        "",
        "> 本文由 **留文 · WENL SCRIBE** 自动转录生成。",
        "",
    ])


def summary_markdown(result):
    claims = result.get("claims") or []
    if claims:
        sections = []
        for index, item in enumerate(claims, 1):
            start = item.get("start")
            time_link = video_time_link(result["source_url"], start) if start is not None else result["source_url"]
            sections.extend([
                f"### {index:02d}｜{item['claim']}",
                "",
                f"**内容类型：** {item.get('kind', '观点')}  ",
                f"**原文位置：** [{timestamp_text(start)}–{timestamp_text(item.get('end'))}]({time_link})  " if start is not None else "**原文位置：** 旧任务无时间戳  ",
                "",
                "> **原文依据**",
                ">",
                markdown_quote(item.get("evidence", "")),
                "",
            ])
        points = "\n".join(sections)
    else:
        points = "\n".join(f"{index}. {point}" for index, point in enumerate(result.get("key_points", []), 1)) or "暂无可用观点。"
    outline = result.get("outline") or []
    outline_sections = []
    for index, item in enumerate(outline, 1):
        outline_sections.extend([
            f"### {index:02d}｜{item.get('title', '未命名章节')}",
            "",
            str(item.get("content", "")).strip(),
            "",
        ])
    summary_label = "原文重点摘录" if result.get("summary_type") == "extractive" else "一句话总结"
    document = [
        f"# {result['title']}",
        "",
        "> **内容总结 · 留文**",
        "",
        "---",
        "",
        "## 视频信息",
        "",
        "| 项目 | 内容 |",
        "| :--- | :--- |",
        f"| 视频 | [{markdown_table_cell(result['title'])}]({result['source_url']}) |",
        f"| 作者 | {markdown_table_cell(result.get('author', '未知'))} |",
        f"| 时长 | {timestamp_text(result.get('duration'))} |",
        f"| 总结方式 | {markdown_table_cell(result.get('method', '未知'))} |",
        "",
        f"## {summary_label}",
        "",
        markdown_quote(result.get("summary", "")),
        "",
        "## 核心观点与原文依据",
        "",
        points,
        "",
    ]
    if outline_sections:
        document.extend(["---", "", "## 内容脉络", "", *outline_sections])
    document.extend([
        "---",
        "",
        "> [!NOTE]",
        "> 本文由 **留文 · WENL SCRIBE** 自动转录与总结生成。重要信息请点击时间戳回看原始内容核对。",
        "",
    ])
    return "\n".join(document)


def markdown_quote(value):
    lines = str(value or "").strip().splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def markdown_table_cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def video_time_link(source_url, seconds):
    parsed = urllib.parse.urlsplit(str(source_url or ""))
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if key != "t"]
    query.append(("t", str(max(0, int(float(seconds or 0))))))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))


def export_filename(result, kind):
    title = str((result or {}).get("title") or "未命名视频")
    title = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = title[:100].rstrip(" .") or "未命名视频"
    label = "逐字稿" if kind == "transcript" else "总结"
    return f"{title}{label}留文.md"


def content_disposition(filename):
    encoded = urllib.parse.quote(filename, safe="")
    fallback = "wenl-transcript.md" if "逐字稿" in filename else "wenl-summary.md"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def resummarize_job(job_id, mode):
    task = TASKS.get(job_id)
    if not task or not task.get("transcript_segments"):
        raise ValueError("任务结果不存在")
    with TASK_LOCK:
        task["summary_mode"] = "local" if mode == "local" else "cloud"
        task["status"] = "pending"
        task["stage"] = "pending"
        task["progress"] = 82
        task["message"] = "逐字稿已保留，正在准备重新总结"
        task["updated_at"] = now_ms()
        task.pop("error", None)
        task.pop("error_info", None)
        CANCEL_EVENTS[job_id] = threading.Event()
        save_task(task)
    threading.Thread(target=run_job, args=(job_id, "summary"), daemon=True).start()
    return public_task(task)


def cancel_job(job_id):
    task = TASKS.get(job_id)
    if not task:
        raise ValueError("任务不存在")
    if task.get("status") in ("completed", "partial", "failed", "cancelled"):
        return public_task(task)
    CANCEL_EVENTS.setdefault(job_id, threading.Event()).set()
    task["message"] = "正在安全取消，已完成的数据会保留"
    task["updated_at"] = now_ms()
    save_task(task)
    log_task(job_id, "cancel_requested", stage=task.get("stage"))
    return public_task(task)


def retry_job(job_id, from_stage="auto"):
    task = TASKS.get(job_id)
    if not task:
        raise ValueError("任务不存在")
    if task.get("status") in ("processing", "pending"):
        raise ValueError("任务正在处理中，不能重复执行")
    resume = "summary" if from_stage in ("auto", "summary") and task.get("transcript_segments") else "auto"
    if from_stage == "transcription":
        resume = "auto"
        task.pop("transcript_segments", None)
        task.pop("result", None)
        RESULTS_BY_ID.pop(job_id, None)
        directory = task_dir(job_id)
        for filename in ("transcript.json", "transcript.md", "summary.json", "summary.md"):
            artifact = directory / filename
            if artifact.exists():
                artifact.unlink()
    with TASK_LOCK:
        task.update({"status": "pending", "stage": "pending", "progress": 2 if resume == "auto" else 82, "message": "正在从已保存阶段重试", "updated_at": now_ms()})
        task.pop("error", None)
        task.pop("error_info", None)
        CANCEL_EVENTS[job_id] = threading.Event()
        save_task(task)
    log_task(job_id, "retry_requested", from_stage=from_stage, resume=resume)
    threading.Thread(target=run_job, args=(job_id, resume), daemon=True).start()
    return public_task(task)


class Handler(BaseHTTPRequestHandler):
    def origin_allowed(self):
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        return not origin or origin in ALLOWED_ORIGINS

    def cors(self):
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.cors(); self.end_headers(); self.wfile.write(raw)

    def send_markdown(self, markdown, filename):
        raw = ("\ufeff" + markdown).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", content_disposition(filename))
        self.send_header("Content-Length", str(len(raw)))
        self.cors(); self.end_headers(); self.wfile.write(raw)

    def send_image(self, raw, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(raw)))
        self.cors(); self.end_headers(); self.wfile.write(raw)

    def send_static_file(self, path):
        path = Path(path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache" if path.name == "index.html" else "public, max-age=31536000, immutable")
        self.send_header("Content-Security-Policy", "frame-src 'self' https://player.bilibili.com")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def serve_application(self, request_path):
        if not STATIC_DIR.exists():
            return self.send_json(503, {"error": "桌面界面尚未构建，请先运行 npm run desktop:build"})
        relative = urllib.parse.unquote(request_path).lstrip("/") or "index.html"
        candidate = (STATIC_DIR / relative).resolve()
        static_root = STATIC_DIR.resolve()
        try:
            candidate.relative_to(static_root)
        except ValueError:
            return self.send_json(404, {"error": "Not found"})
        if candidate.is_file():
            return self.send_static_file(candidate)
        index = static_root / "index.html"
        if index.is_file() and "." not in Path(relative).name:
            return self.send_static_file(index)
        return self.send_json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        if not self.origin_allowed():
            return self.send_json(403, {"error": "不允许的本地页面来源"})
        self.send_response(204); self.cors(); self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            return self.send_json(200, {"ok": True, "models_loaded": list(MODEL_CACHE), "cloud_summary": load_summary_config()["configured"]})
        if parsed.path == "/api/config":
            return self.send_json(200, public_summary_config())
        if parsed.path == "/api/history":
            items = sorted((public_task(t, False) for t in TASKS.values()), key=lambda t: t.get("created_at", 0), reverse=True)
            return self.send_json(200, {"items": items[:50]})
        if parsed.path == "/api/cover":
            cover_url = (urllib.parse.parse_qs(parsed.query).get("url") or [""])[0]
            hostname = (urllib.parse.urlparse(cover_url).hostname or "").lower()
            if not hostname.endswith("hdslb.com"):
                return self.send_json(400, {"error": "不支持的封面地址"})
            try:
                req = urllib.request.Request(cover_url, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    return self.send_image(response.read(), response.headers.get_content_type())
            except Exception:
                return self.send_json(502, {"error": "封面加载失败"})
        job_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", parsed.path)
        if job_match:
            task = TASKS.get(job_match.group(1))
            return self.send_json(200, public_task(task)) if task else self.send_json(404, {"error": "任务不存在"})
        if parsed.path in ("/api/download/transcript", "/api/download/summary"):
            job_id = (urllib.parse.parse_qs(parsed.query).get("job_id") or [""])[0]
            result = RESULTS_BY_ID.get(job_id)
            if not result:
                return self.send_json(404, {"error": "任务结果不存在，请重新处理视频"})
            if parsed.path.endswith("transcript"):
                return self.send_markdown(transcript_markdown(result), export_filename(result, "transcript"))
            return self.send_markdown(summary_markdown(result), export_filename(result, "summary"))
        if parsed.path == "/api/download/diagnostics":
            job_id = (urllib.parse.parse_qs(parsed.query).get("job_id") or [""])[0]
            task = TASKS.get(job_id)
            log_path = TASK_DIR / job_id / "task.log"
            if not task:
                return self.send_json(404, {"error": "任务不存在"})
            lines = [json.dumps(redact({"event": "task_snapshot", "metadata": task_metadata(task), "status": task_status(task)}), ensure_ascii=False)]
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    try:
                        lines.append(json.dumps(redact(json.loads(line)), ensure_ascii=False))
                    except json.JSONDecodeError:
                        continue
            return self.send_markdown("# 留文任务脱敏诊断日志\n\n```jsonl\n" + "\n".join(lines) + "\n```\n", f"diagnostics-{job_id[:8]}.md")
        if not parsed.path.startswith("/api/"):
            return self.serve_application(parsed.path)
        self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if not self.origin_allowed():
            return self.send_json(403, {"error": "不允许的本地页面来源"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/config":
                return self.send_json(200, save_summary_config(payload))
            if self.path == "/api/config/models":
                return self.send_json(200, list_summary_models(payload.get("selection_mode", "auto")))
            if self.path == "/api/config/test":
                return self.send_json(200, test_summary_service())
            resummary_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/resummarize", self.path)
            if resummary_match:
                mode = str(payload.get("mode", "cloud"))
                if mode not in ("cloud", "local"):
                    raise ValueError("不支持的总结方式")
                return self.send_json(202, resummarize_job(resummary_match.group(1), mode))
            cancel_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", self.path)
            if cancel_match:
                return self.send_json(202, cancel_job(cancel_match.group(1)))
            retry_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/retry", self.path)
            if retry_match:
                from_stage = str(payload.get("from_stage", "auto"))
                if from_stage not in ("auto", "summary", "transcription"):
                    raise ValueError("不支持的重试阶段")
                return self.send_json(202, retry_job(retry_match.group(1), from_stage))
            if self.path not in ("/api/jobs", "/api/transcribe", "/api/summarize"):
                return self.send_json(404, {"error": "Not found"})
            link = str(payload.get("url", "")).strip()
            if not link:
                raise ValueError("请先粘贴视频链接或分享文案")
            if self.path == "/api/jobs":
                return self.send_json(202, create_job(
                    link,
                    payload.get("model", "small"),
                    payload.get("summary_mode", "auto"),
                    payload.get("language", "auto"),
                ))
            video = get_video(link)
            segments = get_subtitles(video)
            if not segments:
                temp_job = uuid.uuid4().hex
                CANCEL_EVENTS[temp_job] = threading.Event()
                segments, _ = transcribe(temp_job, video, payload.get("model", "small"), payload.get("language", "auto"), lambda *args: None)
            transcript = segments_text(segments)
            summary = local_summary(video["title"], transcript, segments)
            job_id = uuid.uuid4().hex
            result = {**video, **summary, "method": "兼容接口", "transcript": transcript, "segments": segments, "job_id": job_id}
            RESULTS_BY_ID[job_id] = result
            return self.send_json(200, result)
        except TaskError as exc:
            self.send_json(400, {"error": str(exc), "code": exc.code, "stage": exc.stage, "retryable": exc.retryable})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            if self.path.startswith("/api/config") or self.path.endswith("/resummarize"):
                self.send_json(400, {"error": f"总结服务返回错误 {exc.code}：{http_error_message(exc)}"})
            else:
                self.send_json(400, {"error": f"视频服务返回错误 {exc.code}，请确认视频可以公开访问"})
        except Exception as exc:
            self.send_json(500, {"error": f"处理失败：{exc}"})

    def do_DELETE(self):
        if not self.origin_allowed():
            return self.send_json(403, {"error": "不允许的本地页面来源"})
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", urllib.parse.urlparse(self.path).path)
        if not match:
            return self.send_json(404, {"error": "Not found"})
        job_id = match.group(1)
        with TASK_LOCK:
            task = TASKS.get(job_id)
            if task and task.get("status") in ("pending", "processing"):
                return self.send_json(409, {"error": "任务正在处理，请先取消，待状态变为已取消后再删除"})
            TASKS.pop(job_id, None); RESULTS_BY_ID.pop(job_id, None)
            CANCEL_EVENTS.pop(job_id, None)
            directory = TASK_DIR / job_id
            if directory.exists():
                resolved = directory.resolve()
                if resolved.parent == TASK_DIR.resolve():
                    shutil.rmtree(resolved)
            legacy_path = TASK_DIR / f"{job_id}.json"
            if legacy_path.exists(): legacy_path.unlink()
        self.send_json(200, {"ok": True})

    def log_message(self, fmt, *args):
        if sys.stdout:
            print(f"[backend] {fmt % args}")


def create_server(host="127.0.0.1", port=8765):
    load_tasks()
    return ThreadingHTTPServer((host, port), Handler)


def serve(host="127.0.0.1", port=8765):
    server = create_server(host, port)
    if sys.stdout:
        print(f"WENL Scribe backend: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
