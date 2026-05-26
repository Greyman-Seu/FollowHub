import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-enrich" / "rss_enrich.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_enrich", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RssEnrichSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_enrich_payload_emits_agent_completion_when_chinese_fields_missing(self):
        payload = {
            "items": [
                {
                    "id": "wechat:1",
                    "title": "Example",
                    "summary": "This is an example summary.",
                    "content_text": "This is an example content body.",
                }
            ]
        }
        enriched = self.module.enrich_payload(payload)
        self.assertEqual(len(enriched["entries"]), 1)
        self.assertTrue(enriched["agent_completion"]["required"])
        self.assertEqual(enriched["agent_completion"]["task_count"], 1)

    def test_enrich_payload_skips_agent_completion_when_fields_present(self):
        payload = {
            "items": [
                {
                    "id": "wechat:1",
                    "title": "Example",
                    "summary": "This is an example summary.",
                    "content_text": "This is an example content body.",
                    "one_liner_zh": "一句话。",
                    "summary_cn": "中文摘要。",
                }
            ]
        }
        enriched = self.module.enrich_payload(payload)
        self.assertFalse(enriched["agent_completion"]["required"])
        self.assertEqual(enriched["agent_completion"]["task_count"], 0)

    def test_cli_enrich_reports_agent_completion_task_count(self):
        payload = {
            "items": [
                {
                    "id": "wechat:1",
                    "title": "Example",
                    "summary": "This is an example summary.",
                    "content_text": "This is an example content body.",
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
                    "enrich",
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
            summary = json.loads(result.stdout)
            self.assertTrue(summary["agent_completion_required"])
            self.assertEqual(summary["agent_completion_task_count"], 1)


if __name__ == "__main__":
    unittest.main()
