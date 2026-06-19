import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import importlib.util


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-fetch" / "rss_fetch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_fetch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RssFetchSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_cli_fetch_preserves_summary_as_content_text(self):
        payload = {
            "items": [
                {
                    "id": "wechat:1",
                    "summary": "Example summary",
                    "content_text": "",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "fetch",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            fetched = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(fetched["items"][0]["content_text"], "Example summary")

    def test_fetch_item_content_fetches_html_and_extracts_text(self):
        item = {
            "id": "wechat:1",
            "url": "https://example.com/post",
            "summary": "Short summary",
            "content_text": "",
        }
        with mock.patch.object(self.module, "fetch_text", return_value="<html><body><h1>Hello</h1><p>World</p></body></html>"):
            fetched = self.module.fetch_item_content(item)
        self.assertEqual(" ".join(fetched["content_text"].split()), "Hello World")
        self.assertEqual(fetched["fetch_status"], "fetched-html")

    def test_fetch_item_content_falls_back_to_summary_on_error(self):
        item = {
            "id": "wechat:1",
            "url": "https://example.com/post",
            "summary": "Short summary",
            "content_text": "",
        }
        with mock.patch.object(self.module, "fetch_text", side_effect=RuntimeError("boom")):
            fetched = self.module.fetch_item_content(item)
        self.assertEqual(fetched["content_text"], "Short summary")
        self.assertEqual(fetched["fetch_status"], "fallback-summary")

    def test_fetch_item_content_preserves_clean_summary_for_x(self):
        item = {
            "id": "x:1",
            "source_type": "x",
            "url": "https://example.com/post",
            "summary": "<p>Hello <a href=\"https://example.com\">world</a></p>",
            "content_text": "",
        }
        with mock.patch.object(self.module, "fetch_text") as mocked_fetch:
            fetched = self.module.fetch_item_content(item)
        mocked_fetch.assert_not_called()
        self.assertEqual(fetched["content_text"], "Hello world")
        self.assertEqual(fetched["fetch_status"], "preserved-summary")

    def test_fetch_item_content_preserves_clean_summary_for_wechat(self):
        item = {
            "id": "wechat:1",
            "source_type": "wechat",
            "url": "https://mp.weixin.qq.com/s?id=1",
            "summary": "<p>解决方案或许在于「循环」。</p>",
            "content_text": "",
        }
        with mock.patch.object(self.module, "fetch_text") as mocked_fetch:
            fetched = self.module.fetch_item_content(item)
        mocked_fetch.assert_not_called()
        self.assertEqual(fetched["content_text"], "解决方案或许在于「循环」。")
        self.assertEqual(fetched["fetch_status"], "preserved-summary")

    def test_fetch_item_content_falls_back_when_wechat_block_page_detected(self):
        item = {
            "id": "wechat:1",
            "source_type": "wechat",
            "url": "https://mp.weixin.qq.com/s?id=1",
            "summary": "",
            "content_text": "",
            "title": "微信标题",
        }
        block_html = "<html><body>环境异常 当前环境异常，完成验证后即可继续访问。 去验证 微信公众平台 secitptpage/verify.html</body></html>"
        with mock.patch.object(self.module, "fetch_text", return_value=block_html):
            fetched = self.module.fetch_item_content(item)
        self.assertEqual(fetched["content_text"], "微信标题")
        self.assertEqual(fetched["fetch_status"], "fallback-blocked")

    def test_fetch_items_parallel_preserves_input_order(self):
        items = [
            {"id": "1", "url": "https://example.com/1", "summary": "a", "content_text": ""},
            {"id": "2", "url": "https://example.com/2", "summary": "b", "content_text": ""},
            {"id": "3", "url": "https://example.com/3", "summary": "c", "content_text": ""},
        ]

        def fake_fetch_item(item, *, request_timeout_seconds=30):
            return {"id": item["id"], "content_text": f"text-{item['id']}", "fetch_status": "fetched-html"}

        with mock.patch.object(self.module, "fetch_item_content", side_effect=fake_fetch_item):
            fetched = self.module.fetch_items(items, max_workers=3, request_timeout_seconds=12)

        self.assertEqual([row["id"] for row in fetched], ["1", "2", "3"])
        self.assertEqual([row["content_text"] for row in fetched], ["text-1", "text-2", "text-3"])

    def test_cli_fetch_reports_worker_and_timeout(self):
        payload = {
            "items": [
                {
                    "id": "wechat:1",
                    "summary": "Example summary",
                    "content_text": "",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "fetch",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--max-workers",
                    "4",
                    "--request-timeout-seconds",
                    "11",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            fetched = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(fetched["max_workers"], 4)
            self.assertEqual(fetched["request_timeout_seconds"], 11)


if __name__ == "__main__":
    unittest.main()
