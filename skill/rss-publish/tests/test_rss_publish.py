import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-publish" / "rss_publish.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_publish", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RssPublishSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_build_daily_injects_date_before_follow_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            digest_path = tmp / "daily-digest.json"
            output_dir = tmp / "publish-out"
            digest_path.write_text(
                json.dumps(
                    {
                        "summary": "Selected 1 RSS stories for today.",
                        "highlights": [],
                        "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                        "sections": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fake_proc = mock.MagicMock(stdout='{"ok": true}', returncode=0)
            with mock.patch.object(self.module, "run_command", return_value=fake_proc):
                rc = self.module.main(
                    [
                        "build-daily",
                        "--input",
                        str(digest_path),
                        "--output-dir",
                        str(output_dir),
                        "--date",
                        "2026-06-18",
                    ]
                )

            self.assertEqual(rc, 0)
            payload = json.loads(digest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["date"], "2026-06-18")


if __name__ == "__main__":
    unittest.main()
