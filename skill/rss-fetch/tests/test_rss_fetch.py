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


if __name__ == "__main__":
    unittest.main()
