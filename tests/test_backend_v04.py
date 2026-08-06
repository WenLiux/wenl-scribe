import io
import importlib.util
import json
import pathlib
import tempfile
import unittest
import urllib.error


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wenl_backend", ROOT / "backend" / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class BackendV04Tests(unittest.TestCase):
    def test_resolve_page_defaults_and_normalizes(self):
        self.assertEqual(server.resolve_page("https://www.bilibili.com/video/BV1xx411c7mD?p=3"), 3)
        self.assertEqual(server.resolve_page("https://www.bilibili.com/video/BV1xx411c7mD?p=0"), 1)
        self.assertEqual(server.resolve_page("https://www.bilibili.com/video/BV1xx411c7mD?p=oops"), 1)

    def test_get_video_selects_requested_page(self):
        original_resolve_bvid = server.resolve_bvid
        original_request_json = server.request_json
        try:
            server.resolve_bvid = lambda _link: ("BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
            server.request_json = lambda _url, **_kwargs: {
                "code": 0,
                "data": {
                    "title": "多 P 测试",
                    "owner": {"name": "测试作者"},
                    "pic": "https://example.com/cover.jpg",
                    "duration": 30,
                    "pages": [
                        {"cid": 101, "duration": 10},
                        {"cid": 202, "duration": 20},
                    ],
                },
            }
            video = server.get_video("https://example.com")
            self.assertEqual(video["page"], 2)
            self.assertEqual(video["cid"], 202)
            self.assertEqual(video["duration"], 20)
            self.assertEqual(video["source_url"], "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
        finally:
            server.resolve_bvid = original_resolve_bvid
            server.request_json = original_request_json

    def test_evidence_spanning_segments_keeps_time_range(self):
        segments = [
            {"start": 10, "end": 14, "text": "政策调整需要观察", "source": "test"},
            {"start": 14, "end": 19, "text": "居民收入和就业变化", "source": "test"},
        ]
        match = server.locate_evidence("需要观察居民收入", segments)
        self.assertIsNotNone(match)
        self.assertEqual(match["start"], 12.0)
        self.assertEqual(match["end"], 19.0)

    def test_evidence_in_later_segment_does_not_seek_to_earlier_window(self):
        segments = [
            {"start": 0, "end": 4, "text": "这是上一段铺垫", "source": "test"},
            {"start": 4, "end": 8, "text": "这里才是核心观点", "source": "test"},
        ]
        match = server.locate_evidence("这里才是核心观点", segments)
        self.assertIsNotNone(match)
        self.assertEqual(match["start"], 4.0)
        self.assertEqual(match["segment_start"], 1)

    def test_summary_rejects_unverified_claims(self):
        segments = [{"start": 0, "end": 5, "text": "原文只说明短期保持稳定。", "source": "test"}]
        payload = {
            "summary": "短期保持稳定。",
            "key_points": [{"claim": "长期快速增长", "evidence": "长期快速增长", "kind": "作者观点"}],
            "outline": [],
        }
        with self.assertRaises(server.TaskError):
            server.validate_ai_summary(payload, segments)

    def test_redaction_removes_common_secret_fields(self):
        clean = server.redact({"api_key": "secret", "authorization": "Bearer secret", "message": "ok"})
        self.assertEqual(clean["api_key"], "[REDACTED]")
        self.assertEqual(clean["authorization"], "[REDACTED]")
        self.assertEqual(clean["message"], "ok")

    def test_explicit_protocol_does_not_infer_sensenova_payload_from_url(self):
        config = {
            "provider": "compatible",
            "protocol": "openai_chat",
            "base_url": "https://example.test/v1/llm",
            "model": "example-model",
            "api_key": "test-key",
            "capabilities": {"structured_output": "prompt_json"},
        }
        prepared = server.get_adapter(config).prepare(
            config,
            server.LLMRequest(model="example-model", prompt="测试", schema={"type": "object"}),
        )
        self.assertEqual(prepared.endpoint, "https://example.test/v1/llm/chat/completions")
        self.assertIsInstance(prepared.payload["messages"][0]["content"], str)
        self.assertNotIn("max_new_tokens", prepared.payload)
        self.assertNotIn("response_format", prepared.payload)

    def test_model_discovery_supports_openai_and_ollama_endpoints(self):
        openai_config = {"provider": "openai", "protocol": "openai_chat", "base_url": "https://example.test/v1"}
        gemini_config = {"provider": "gemini", "protocol": "gemini_openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}
        ollama_config = {"provider": "compatible", "protocol": "ollama", "base_url": "http://127.0.0.1:11434/v1"}
        self.assertTrue(server.adapter_capabilities("openai_chat")["models"])
        self.assertTrue(server.adapter_capabilities("gemini_openai")["models"])
        self.assertTrue(server.adapter_capabilities("ollama")["models"])
        self.assertEqual(server.get_adapter(openai_config).models_endpoint(openai_config), "https://example.test/v1/models")
        self.assertEqual(server.get_adapter(gemini_config).models_endpoint(gemini_config), "https://generativelanguage.googleapis.com/v1beta/openai/models")
        self.assertEqual(server.get_adapter(ollama_config).models_endpoint(ollama_config), "http://127.0.0.1:11434/api/tags")

    def test_switching_provider_reuses_existing_target_credential(self):
        original_config_path = server.CONFIG_PATH
        original_credentials_path = server.CREDENTIALS_PATH
        original_read_secret = server.read_secret
        original_write_secret = server.write_secret
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                server.CONFIG_PATH = root / "config.json"
                server.CREDENTIALS_PATH = root / "credentials.json"
                secrets = {"sensenova:sensenova_compatible": "sense-key"}
                server.read_secret = lambda _path, reference: secrets.get(reference, "")
                server.write_secret = lambda _path, reference, value: secrets.__setitem__(reference, value)
                server.CONFIG_PATH.write_text(
                    json.dumps({"provider": "compatible", "protocol": "openai_chat", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:8b"}),
                    encoding="utf-8",
                )
                result = server.save_summary_config({
                    "provider": "sensenova",
                    "protocol": "sensenova_compatible",
                    "base_url": "https://api.sensenova.cn/compatible-mode/v2",
                    "model": "SenseChat-5",
                })
                self.assertTrue(result["has_api_key"])
                self.assertEqual(result["key_hint"], "••••-key")
                saved = json.loads(server.CONFIG_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["credential_ref"], "sensenova:sensenova_compatible")
        finally:
            server.CONFIG_PATH = original_config_path
            server.CREDENTIALS_PATH = original_credentials_path
            server.read_secret = original_read_secret
            server.write_secret = original_write_secret

    def test_protocol_must_match_provider_when_explicit(self):
        with self.assertRaises(ValueError):
            server.protocol_for_config({"provider": "gemini", "protocol": "sensenova_native"})

    def test_legacy_sensenova_url_migrates_to_compatible_protocol(self):
        self.assertEqual(
            server.protocol_for_config({"provider": "sensenova", "base_url": "https://token.sensenova.cn/v1"}),
            "sensenova_compatible",
        )

    def test_connection_probe_does_not_require_summary_claims(self):
        original_load = server.load_summary_config
        original_request = server.request_json
        captured = {}
        try:
            server.load_summary_config = lambda: {
                "provider": "compatible",
                "protocol": "openai_chat",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:8b",
                "api_key": "",
                "configured": True,
                "capabilities": {"structured_output": "prompt_json"},
            }

            def fake_request(url, payload=None, headers=None, timeout=30):
                captured.update({"url": url, "payload": payload, "timeout": timeout})
                return {"choices": [{"message": {"content": "服务已响应，但没有输出总结观点。"}}]}

            server.request_json = fake_request
            result = server.test_summary_service()
            self.assertTrue(result["ok"])
            self.assertEqual(captured["timeout"], 60)
            self.assertEqual(captured["url"], "http://127.0.0.1:11434/v1/chat/completions")
        finally:
            server.load_summary_config = original_load
            server.request_json = original_request

    def test_http_400_is_invalid_request_and_not_retryable(self):
        body = io.BytesIO(b'{"error":{"message":"unsupported parameter"}}')
        error = urllib.error.HTTPError("https://example.test/v1/chat/completions", 400, "Bad Request", {}, body)
        info = server.error_info(error, "summarizing")
        self.assertEqual(info["code"], "API_INVALID_REQUEST")
        self.assertFalse(info["retryable"])
        error.close()

    def test_normalized_response_keeps_usage_and_request_metadata(self):
        result = server.normalize_response({
            "id": "req-123",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 12},
        })
        self.assertEqual(result.text, "{}")
        self.assertEqual(result.request_id, "req-123")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage["total_tokens"], 12)

    def test_sensenova_403_is_reported_as_permission_error(self):
        body = io.BytesIO(b'{"error":{"code":7,"message":"Forbidden"}}')
        error = urllib.error.HTTPError(
            "https://api.sensenova.cn/v1/llm/chat-completions",
            403,
            "Forbidden",
            {},
            body,
        )
        info = server.error_info(error, "summarizing")
        self.assertEqual(info["code"], "API_PERMISSION_DENIED")
        self.assertIn("商汤错误码 7", info["message"])
        error.close()

    def test_markdown_exports_use_readable_layout_and_title_filename(self):
        result = {
            "title": "**白发魔女",
            "author": "测试作者",
            "duration": 125,
            "source_url": "https://www.bilibili.com/video/BV1test?p=2",
            "method": "Whisper + AI 总结",
            "summary_type": "generative",
            "summary": "这是总体总结。",
            "segments": [{"start": 65, "end": 70, "text": "这是原文。"}],
            "transcript": "这是原文。",
            "claims": [{"claim": "核心观点", "evidence": "这是原文。", "kind": "作者观点", "start": 65, "end": 70}],
            "outline": [{"title": "第一部分", "content": "内容脉络。"}],
        }
        transcript = server.transcript_markdown(result)
        summary = server.summary_markdown(result)
        self.assertIn("## 视频信息", transcript)
        self.assertIn("## 阅读说明", transcript)
        self.assertIn("[01:05](https://www.bilibili.com/video/BV1test?p=2&t=65)", transcript)
        self.assertIn("## 核心观点与原文依据", summary)
        self.assertIn("## 内容脉络", summary)
        self.assertIn("> **原文依据**", summary)
        self.assertEqual(server.export_filename(result, "summary"), "白发魔女总结留文.md")
        self.assertEqual(server.export_filename(result, "transcript"), "白发魔女逐字稿留文.md")
        disposition = server.content_disposition("白发魔女总结留文.md")
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertIn("%E7%99%BD%E5%8F%91%E9%AD%94%E5%A5%B3", disposition)

    def test_transcript_can_be_saved_before_summary_exists(self):
        original_task_dir = server.TASK_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                server.TASK_DIR = pathlib.Path(temp)
                segments = [{"start": 0, "end": 4, "text": "这是一段逐字稿。", "source": "test"}]
                result = {
                    "job_id": "a" * 32,
                    "title": "保存测试",
                    "author": "测试",
                    "duration": 4,
                    "source_url": "https://example.com/video",
                    "method": "测试转录",
                    "transcript": "这是一段逐字稿。",
                    "segments": segments,
                }
                task = {
                    "job_id": "a" * 32,
                    "status": "processing",
                    "stage": "cleaning",
                    "progress": 80,
                    "message": "正在保存逐字稿",
                    "created_at": 1,
                    "model": "small",
                    "summary_mode": "auto",
                    "language": "zh",
                    "transcript_segments": segments,
                    "result": result,
                }
                server.save_task(task)
                directory = server.TASK_DIR / task["job_id"]
                self.assertTrue((directory / "transcript.json").exists())
                self.assertTrue((directory / "transcript.md").exists())
                self.assertFalse((directory / "summary.json").exists())
                self.assertFalse((directory / "summary.md").exists())
        finally:
            server.TASK_DIR = original_task_dir

    def test_sensenova_uses_openai_compatible_json_mode(self):
        original_request_json = server.request_json
        captured = {}
        try:
            def fake_request(url, payload=None, headers=None, timeout=30):
                captured.update({"url": url, "payload": payload, "headers": headers})
                content = json.dumps({"summary": "测试总结", "key_points": [], "outline": []}, ensure_ascii=False)
                return {"choices": [{"message": {"content": content}}]}

            server.request_json = fake_request
            result = server.request_summary(
                {"provider": "sensenova", "base_url": "https://token.sensenova.cn/v1", "model": "sensenova-6.7-flash-lite", "api_key": "sk-test"},
                "测试标题",
                "[00:00-00:04] 测试逐字稿",
            )
            self.assertEqual(result["summary"], "测试总结")
            self.assertEqual(captured["url"], "https://token.sensenova.cn/v1/chat/completions")
            self.assertNotIn("response_format", captured["payload"])
            self.assertEqual(captured["payload"]["max_tokens"], 4096)
            self.assertFalse(captured["payload"]["stream"])
            self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        finally:
            server.request_json = original_request_json

    def test_sensenova_model_list_normalizes_permissions_and_selects_chat_model(self):
        original_load = server.load_summary_config
        original_request_json = server.request_json
        original_save = server.save_summary_config
        original_public = server.public_summary_config
        saved = []
        try:
            config = {
                "provider": "sensenova",
                "protocol": "sensenova_compatible",
                "base_url": "https://api.sensenova.cn/compatible-mode/v2",
                "model": "unavailable-model",
                "api_key": "sk-test",
                "configured": True,
            }
            server.load_summary_config = lambda: config

            def fake_request(url, *args, **_kwargs):
                if url.endswith("/chat/completions"):
                    return {"choices": [{"message": {"content": "ok"}}]}
                return {
                    "data": [
                        {"id": "image-model", "permission": [{"allow_chat": False}]},
                        {"id": "chat-model", "permission": [{"allow_chat": True}]},
                    ]
                }

            server.request_json = fake_request
            server.save_summary_config = lambda payload: saved.append(payload)
            server.public_summary_config = lambda: {"model": "chat-model", "configured": True}
            result = server.list_summary_models()
            self.assertEqual(result["selected_model"], "chat-model")
            self.assertEqual(result["models"][0]["allow_chat"], False)
            self.assertEqual(result["models"][1]["allow_chat"], True)
            self.assertEqual(saved[0]["model"], "chat-model")
        finally:
            server.load_summary_config = original_load
            server.request_json = original_request_json
            server.save_summary_config = original_save
            server.public_summary_config = original_public

    def test_sensenova_manual_model_validation_does_not_fallback(self):
        original_load = server.load_summary_config
        original_request_json = server.request_json
        original_probe = server.probe_summary_service
        original_save = server.save_summary_config
        saved = []
        try:
            config = {
                "provider": "sensenova",
                "protocol": "sensenova_compatible",
                "base_url": "https://token.sensenova.cn/v1",
                "model": "glm-5.2",
                "api_key": "sk-test",
                "configured": True,
            }
            server.load_summary_config = lambda: config
            server.request_json = lambda url, *args, **_kwargs: {
                "data": [{"id": "deepseek-v4-flash"}, {"id": "glm-5.2"}]
            }

            def failing_probe(candidate):
                raise server.TaskError("API_PROVIDER_ERROR", "模型返回为空", "testing", retryable=False)

            server.probe_summary_service = failing_probe
            server.save_summary_config = lambda payload: saved.append(payload)
            with self.assertRaises(server.TaskError) as raised:
                server.list_summary_models("manual")
            self.assertIn("glm-5.2", str(raised.exception))
            self.assertEqual(saved, [])
        finally:
            server.load_summary_config = original_load
            server.request_json = original_request_json
            server.probe_summary_service = original_probe
            server.save_summary_config = original_save

    def test_sensenova_probe_uses_reasoning_safe_output_budget(self):
        original_request_json = server.request_json
        captured = {}
        try:
            def fake_request(url, payload=None, headers=None, timeout=30):
                captured.update({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
                return {"choices": [{"message": {"content": "{\"ok\":true}"}, "finish_reason": "stop"}]}

            server.request_json = fake_request
            server.probe_summary_service({
                "provider": "sensenova",
                "protocol": "sensenova_compatible",
                "base_url": "https://token.sensenova.cn/v1",
                "model": "glm-5.2",
                "api_key": "sk-test",
            })
            self.assertEqual(captured["payload"]["max_tokens"], server.MODEL_PROBE_MAX_OUTPUT_TOKENS)
            self.assertEqual(server.MODEL_PROBE_MAX_OUTPUT_TOKENS, 256)
        finally:
            server.request_json = original_request_json

    def test_sensenova_probe_retries_when_reasoning_hits_output_limit(self):
        original_request_json = server.request_json
        budgets = []
        try:
            def fake_request(url, payload=None, headers=None, timeout=30):
                budgets.append(payload.get("max_tokens") or payload.get("max_completion_tokens"))
                if len(budgets) == 1:
                    return {"choices": [{"message": {"content": "", "reasoning_content": "thinking"}, "finish_reason": "length"}]}
                return {"choices": [{"message": {"content": "{\"ok\":true}"}, "finish_reason": "stop"}]}

            server.request_json = fake_request
            result = server.probe_summary_service({
                "provider": "sensenova",
                "protocol": "sensenova_compatible",
                "base_url": "https://token.sensenova.cn/v1",
                "model": "sensenova-6.7-flash-lite",
                "api_key": "sk-test",
            })
            self.assertEqual(result.text, "{\"ok\":true}")
            self.assertEqual(budgets, [server.MODEL_PROBE_MAX_OUTPUT_TOKENS, server.MODEL_PROBE_RETRY_OUTPUT_TOKENS])
        finally:
            server.request_json = original_request_json

    def test_sensenova_model_list_falls_back_from_native_to_compatible_gateway(self):
        original_load = server.load_summary_config
        original_request_json = server.request_json
        original_save = server.save_summary_config
        original_public = server.public_summary_config
        saved = []
        try:
            config = {
                "provider": "sensenova",
                "protocol": "sensenova_native",
                "base_url": "https://api.sensenova.cn/v1/llm",
                "model": "legacy-model",
                "api_key": "sk-test",
                "configured": True,
            }
            server.load_summary_config = lambda: config

            def fake_request(url, *args, **_kwargs):
                if url.endswith("/v1/llm/models"):
                    raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b'{"error":{"code":7}}'))
                if url.endswith("/chat/completions"):
                    return {"choices": [{"message": {"content": "ok"}}]}
                return {"data": [{"id": "compatible-chat", "allow_chat": True}]}

            server.request_json = fake_request
            server.save_summary_config = lambda payload: saved.append(payload)
            server.public_summary_config = lambda: {"protocol": "sensenova_compatible", "model": "compatible-chat", "configured": True}
            result = server.list_summary_models()
            self.assertEqual(result["selected_model"], "compatible-chat")
            self.assertEqual(saved[0]["protocol"], "sensenova_compatible")
            self.assertEqual(saved[0]["base_url"], "https://api.sensenova.cn/compatible-mode/v2")
            self.assertEqual(saved[0]["api_key"], "sk-test")
        finally:
            server.load_summary_config = original_load
            server.request_json = original_request_json
            server.save_summary_config = original_save
            server.public_summary_config = original_public

    def test_sensenova_official_endpoint_uses_documented_path_and_response_envelope(self):
        original_request_json = server.request_json
        captured = {}
        try:
            def fake_request(url, payload=None, headers=None, timeout=30):
                captured.update({"url": url, "payload": payload, "headers": headers})
                content = json.dumps({"summary": "官方接口测试", "key_points": [], "outline": []}, ensure_ascii=False)
                return {"data": {"choices": [{"message": {"content": [{"type": "text", "text": content}]}}]}}

            server.request_json = fake_request
            result = server.request_summary(
                {"provider": "sensenova", "base_url": "https://api.sensenova.cn/v1/llm", "model": "deepseek-v4-flash", "api_key": "token-test"},
                "测试标题",
                "[00:00-00:04] 官方接口逐字稿",
            )
            self.assertEqual(result["summary"], "官方接口测试")
            self.assertEqual(captured["url"], "https://api.sensenova.cn/v1/llm/chat-completions")
            self.assertEqual(captured["payload"]["model"], "deepseek-v4-flash")
            self.assertEqual(captured["payload"]["max_new_tokens"], 4096)
            self.assertNotIn("response_format", captured["payload"])
            self.assertEqual(captured["headers"]["Authorization"], "Bearer token-test")
        finally:
            server.request_json = original_request_json

    def test_response_text_accepts_sensenova_data_choices(self):
        content = json.dumps({"summary": "嵌套响应", "key_points": [], "outline": []}, ensure_ascii=False)
        result = {"data": {"choices": [{"message": {"content": [{"type": "text", "text": content}]}}]}}
        self.assertEqual(server.response_text(result), content)
        self.assertEqual(server.response_text({"data": {"choices": [{"message": content}]}}), content)


if __name__ == "__main__":
    unittest.main()
