import importlib.util
import json
import pathlib
import tempfile
import unittest


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
        self.assertEqual(match["start"], 10.0)
        self.assertEqual(match["end"], 19.0)

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
            self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
            self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        finally:
            server.request_json = original_request_json


if __name__ == "__main__":
    unittest.main()
