import io
import importlib.util
import json
import pathlib
import tempfile
import unittest
import urllib.error
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wenl_backend", ROOT / "backend" / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class BackendV04Tests(unittest.TestCase):
    def test_origin_allows_configured_dev_page_and_packaged_app_same_port(self):
        self.assertTrue(server.is_allowed_origin("http://localhost:3001", 8766))
        self.assertTrue(server.is_allowed_origin("http://127.0.0.1:3001", 8766))
        self.assertTrue(server.is_allowed_origin("http://localhost:8766", 8766))
        self.assertTrue(server.is_allowed_origin("http://127.0.0.1:8766/", 8766))
        self.assertTrue(server.is_allowed_origin("http://[::1]:8766", 8766))
        self.assertFalse(server.is_allowed_origin("http://localhost:8765", 8766))
        self.assertFalse(server.is_allowed_origin("https://example.com", 8766))

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

    def test_playback_candidates_use_dash_backups_and_rank_audio(self):
        original_request_json = server.request_json
        calls = []
        try:
            def fake_request(url, **_kwargs):
                calls.append(url)
                return {
                    "code": 0,
                    "data": {
                        "dash": {
                            "audio": [
                                {
                                    "id": 30232,
                                    "bandwidth": 69027,
                                    "baseUrl": "https://audio-low.example.test/a.m4s",
                                },
                                {
                                    "id": 30280,
                                    "bandwidth": 83355,
                                    "baseUrl": "https://audio-primary.example.test/a.m4s",
                                    "backupUrl": ["https://audio-backup.example.test/a.m4s"],
                                },
                            ]
                        }
                    },
                }

            server.request_json = fake_request
            candidates = server.playback_media_candidates({
                "bvid": "BV1xx411c7mD",
                "cid": 123,
                "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            })
            self.assertEqual(candidates[0]["label"], "audio-30280")
            self.assertEqual(candidates[0]["urls"], [
                "https://audio-primary.example.test/a.m4s",
                "https://audio-backup.example.test/a.m4s",
            ])
            self.assertEqual(len(calls), 1)
        finally:
            server.request_json = original_request_json

    def test_playback_candidates_fall_back_to_legacy_durl(self):
        original_request_json = server.request_json
        try:
            def fake_request(url, **_kwargs):
                if "fnval=16" in url:
                    return {"code": 0, "data": {"dash": {"audio": []}}}
                return {
                    "code": 0,
                    "data": {
                        "durl": [{
                            "url": "http://upos.example.test/video.flv",
                            "backup_url": ["https://backup.example.test/video.flv"],
                            "size": 2048,
                        }]
                    },
                }

            server.request_json = fake_request
            candidates = server.playback_media_candidates({
                "bvid": "BV1xx411c7mD",
                "cid": 123,
                "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            })
            self.assertEqual(candidates[0]["kind"], "combined")
            self.assertEqual(candidates[0]["total_bytes"], 2048)
            self.assertEqual(candidates[0]["segments"][0], [
                "https://upos.example.test/video.flv",
                "https://backup.example.test/video.flv",
            ])
        finally:
            server.request_json = original_request_json

    def test_download_media_retries_transient_cdn_failure(self):
        original_urlopen = server.urllib.request.urlopen
        payload = b"audio"
        calls = []

        class FakeHeaders:
            def get(self, name, default=None):
                return str(len(payload)) if name == "Content-Length" else default

        class FakeResponse(io.BytesIO):
            headers = FakeHeaders()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        def fake_urlopen(*_args, **_kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise urllib.error.URLError("unexpected eof")
            return FakeResponse(payload)

        try:
            server.urllib.request.urlopen = fake_urlopen
            with tempfile.TemporaryDirectory() as directory:
                path = server.download_media_candidate(
                    "a" * 32,
                    {"source_url": "https://www.bilibili.com/video/BV1xx411c7mD"},
                    {"kind": "audio", "label": "test", "urls": ["https://audio.example.test/a.m4s"], "total_bytes": len(payload)},
                    lambda *_args: None,
                )
                try:
                    self.assertEqual(pathlib.Path(path).read_bytes(), payload)
                finally:
                    pathlib.Path(path).unlink(missing_ok=True)
            self.assertEqual(len(calls), 2)
        finally:
            server.urllib.request.urlopen = original_urlopen

    def test_resolve_bilibili_article_and_reject_lookalike_host(self):
        resolved = server.resolve_bilibili_link("【文章分享】 https://www.bilibili.com/opus/1224392457667477526?from=share")
        self.assertEqual(resolved["content_type"], "article")
        self.assertEqual(resolved["article_id"], "1224392457667477526")
        legacy = server.resolve_bilibili_link("https://www.bilibili.com/read/cv123456")
        self.assertEqual(legacy["article_id"], "cv123456")
        with self.assertRaises(ValueError):
            server.resolve_bilibili_link("https://bilibili.com.example.test/opus/123")

    def test_parse_bilibili_article_extracts_server_rendered_content(self):
        html = """
        <html><head><title>备用标题 - 哔哩哔哩</title><meta property="og:image" content="https://example.test/cover.jpg"></head>
        <body><div class="opus-module-title__text"><span>文章标题</span></div>
        <a class="opus-module-author__name">文章作者</a>
        <div class="opus-module-content opus-paragraph-children">
          <h2>第一部分</h2><p>这是一段足够长的文章正文，用于验证留文能够直接读取 B 站文章而不启动语音转录流程。</p>
          <p>第二段继续说明文章中的关键步骤和注意事项，供后续总结与原文依据校验使用。</p>
          <figure><img data-src="//i0.hdslb.com/bfs/new_dyn/detail.png" alt="网络拓扑图"><figcaption>图一：组网结构</figcaption></figure>
        </div></body></html>
        """
        article = server.parse_bilibili_article(html, "https://www.bilibili.com/opus/123", "123")
        self.assertEqual(article["content_type"], "article")
        self.assertEqual(article["title"], "文章标题")
        self.assertEqual(article["author"], "文章作者")
        self.assertEqual(article["cover"], "https://example.test/cover.jpg")
        self.assertTrue(any(item["text"] == "第一部分" and item["kind"] == "heading" for item in article["segments"]))
        self.assertTrue(any("网络拓扑图" in item["text"] and item["kind"] == "caption" for item in article["segments"]))
        self.assertTrue(all(item["start"] is None for item in article["segments"]))
        image_blocks = [item for item in article["article_blocks"] if item["kind"] == "image"]
        self.assertEqual(len(image_blocks), 1)
        self.assertEqual(image_blocks[0]["image_index"], 0)
        self.assertEqual(image_blocks[0]["image_url"], "https://i0.hdslb.com/bfs/new_dyn/detail.png")

    def test_article_images_are_cached_per_task_and_reject_untrusted_hosts(self):
        original_task_dir = server.TASK_DIR
        original_urlopen = server.urllib.request.urlopen
        payload = b"\x89PNG\r\n\x1a\narticle-image"

        class FakeHeaders:
            def get_content_type(self):
                return "image/png"

            def get(self, name, default=None):
                return str(len(payload)) if name == "Content-Length" else default

        class FakeResponse(io.BytesIO):
            headers = FakeHeaders()

            def geturl(self):
                return "https://i0.hdslb.com/bfs/new_dyn/detail.png"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        try:
            with tempfile.TemporaryDirectory() as directory:
                server.TASK_DIR = pathlib.Path(directory)
                server.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(payload)
                raw, content_type = server.load_article_image("a" * 32, 3, "https://i0.hdslb.com/bfs/new_dyn/detail.png")
                self.assertEqual(raw, payload)
                self.assertEqual(content_type, "image/png")
                self.assertTrue((server.TASK_DIR / ("a" * 32) / "images" / "003.png").exists())
                server.urllib.request.urlopen = lambda *_args, **_kwargs: self.fail("缓存命中时不应再次下载")
                cached, cached_type = server.load_article_image("a" * 32, 3, "https://i0.hdslb.com/bfs/new_dyn/detail.png")
                self.assertEqual(cached, payload)
                self.assertEqual(cached_type, "image/png")
                with self.assertRaises(ValueError):
                    server.load_article_image("a" * 32, 4, "https://hdslb.com.example.test/detail.png")
        finally:
            server.TASK_DIR = original_task_dir
            server.urllib.request.urlopen = original_urlopen

    def test_article_job_skips_subtitles_and_whisper(self):
        original_task_dir = server.TASK_DIR
        original_get_source = server.get_source
        original_get_subtitles = server.get_subtitles
        original_transcribe = server.transcribe
        original_load_summary_config = server.load_summary_config
        job_id = "f" * 32
        try:
            with tempfile.TemporaryDirectory() as directory:
                server.TASK_DIR = pathlib.Path(directory)
                article_segments = [
                    {"start": None, "end": None, "text": "第一段文章正文说明组网目标和实施范围。", "source": "bilibili_article"},
                    {"start": None, "end": None, "text": "第二段文章正文说明具体配置步骤和验证方法。", "source": "bilibili_article"},
                ]
                server.get_source = lambda _link: ({
                    "content_type": "article", "article_id": "123", "title": "文章任务",
                    "author": "测试作者", "duration": 0, "cover": "",
                    "source_url": "https://www.bilibili.com/opus/123",
                }, article_segments)
                server.get_subtitles = lambda _source: self.fail("文章任务不应读取视频字幕")
                server.transcribe = lambda *_args, **_kwargs: self.fail("文章任务不应启动 Whisper")
                server.load_summary_config = lambda: {
                    "provider": "local", "protocol": "local", "model": "", "configured": False,
                }
                server.TASKS[job_id] = {
                    "job_id": job_id, "input": "https://www.bilibili.com/opus/123",
                    "status": "pending", "stage": "pending", "progress": 2, "message": "准备",
                    "model": "small", "language": "auto", "summary_mode": "local",
                    "created_at": server.now_ms(), "updated_at": server.now_ms(),
                }
                server.CANCEL_EVENTS[job_id] = server.threading.Event()
                server.run_job(job_id)
                task = server.TASKS[job_id]
                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["result"]["content_type"], "article")
                self.assertNotIn("video", task["result"])
                self.assertEqual(task["result"]["article"]["articleId"], "123")
                self.assertTrue((server.TASK_DIR / job_id / "transcript.md").exists())
        finally:
            server.TASK_DIR = original_task_dir
            server.get_source = original_get_source
            server.get_subtitles = original_get_subtitles
            server.transcribe = original_transcribe
            server.load_summary_config = original_load_summary_config
            server.TASKS.pop(job_id, None)
            server.CANCEL_EVENTS.pop(job_id, None)
            server.RESULTS_BY_ID.pop(job_id, None)

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

    def test_article_markdown_uses_article_labels_without_timestamps(self):
        result = {
            "content_type": "article",
            "article_id": "123",
            "title": "组网教程",
            "author": "测试作者",
            "duration": 0,
            "source_url": "https://www.bilibili.com/opus/123",
            "method": "B 站文章正文 + 本地原文提要",
            "summary_type": "extractive",
            "summary": "这是文章摘要。",
            "segments": [{"start": None, "end": None, "text": "这是文章原文。"}],
            "transcript": "这是文章原文。",
            "claims": [{"claim": "文章观点", "evidence": "这是文章原文。", "kind": "原文摘录", "start": None, "end": None}],
            "outline": [],
        }
        transcript = server.transcript_markdown(result)
        summary = server.summary_markdown(result)
        self.assertIn("## 文章信息", transcript)
        self.assertIn("## 完整原文", transcript)
        self.assertNotIn("时长", transcript)
        self.assertIn("[查看文章原文](https://www.bilibili.com/opus/123)", summary)
        self.assertNotIn("旧任务无时间戳", summary)
        self.assertEqual(server.export_filename(result, "transcript"), "组网教程原文留文.md")

    def test_article_package_contains_ordered_markdown_and_local_images(self):
        original_load_article_image = server.load_article_image
        result = {
            "job_id": "c" * 32,
            "content_type": "article",
            "article_id": "123",
            "title": "组网/教程",
            "author": "测试作者",
            "source_url": "https://www.bilibili.com/opus/123",
            "method": "B 站文章正文",
            "transcript": "第一段\n第二段",
            "article_blocks": [
                {"kind": "heading", "text": "准备工作"},
                {"kind": "paragraph", "text": "第一段"},
                {"kind": "image", "image_url": "https://i0.hdslb.com/a.png", "alt": "拓扑图", "image_index": 0},
                {"kind": "paragraph", "text": "第二段"},
            ],
        }
        try:
            server.load_article_image = lambda job_id, image_index, image_url: (b"PNG-DATA", "image/png")
            raw = server.build_article_package(result)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(set(archive.namelist()), {"组网教程原文留文.md", "images/001.png"})
                markdown = archive.read("组网教程原文留文.md").decode("utf-8-sig")
                self.assertIn("![拓扑图](images/001.png)", markdown)
                self.assertLess(markdown.index("第一段"), markdown.index("![拓扑图]"))
                self.assertLess(markdown.index("![拓扑图]"), markdown.index("第二段"))
                self.assertEqual(archive.read("images/001.png"), b"PNG-DATA")
            self.assertEqual(server.article_package_filename(result), "组网教程图文留文.zip")
            self.assertIn("wenl-article-package.zip", server.content_disposition("组网教程图文留文.zip"))
        finally:
            server.load_article_image = original_load_article_image

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
