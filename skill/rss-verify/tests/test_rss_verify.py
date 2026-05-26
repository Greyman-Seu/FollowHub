import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "skill" / "rss-verify" / "rss_verify.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rss_verify_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


rss_verify = load_module()


class RssVerifyTests(unittest.TestCase):
    def test_verify_paths_passes_for_valid_publish_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            publish_dir = root / "publish-out"
            (publish_dir / "daily").mkdir(parents=True, exist_ok=True)
            (publish_dir / "sources").mkdir(parents=True, exist_ok=True)
            digest = {
                "date": "2026-05-17",
                "summary": "Selected 1 RSS stories for today.",
                "highlights": ["Robot story"],
                "counts": {"wechat": 1, "x": 0, "arxiv": 0, "bilibili": 0, "rss": 0},
                "stories": [
                    {
                        "story_id": "story:wechat:abc:123:1:xyz",
                        "story_status": "new",
                        "representative_item_id": "entry-1",
                        "title": "Robot story",
                        "summary": "Robot story",
                    }
                ],
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 1,
                        "items": [
                            {
                                "story_id": "story:wechat:abc:123:1:xyz",
                                "story_status": "new",
                                "id": "entry-1",
                                "title": "Robot story",
                                "summary": "Robot story",
                            }
                        ],
                    }
                ],
            }
            for target in [publish_dir / "latest.json", publish_dir / "daily" / "2026-05-17.json"]:
                target.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
            (publish_dir / "manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (publish_dir / "sources" / "wechat.json").write_text(json.dumps({"items": []}), encoding="utf-8")

            result = rss_verify.verify_paths(publish_dir, "2026-05-17")
            self.assertTrue(result["ok"])
            self.assertTrue(result["content_checks"]["ok"])
            self.assertEqual(result["content_checks"]["story_count"], 1)

    def test_verify_paths_accepts_publish_style_digest_without_stories_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            publish_dir = root / "publish-out"
            (publish_dir / "daily").mkdir(parents=True, exist_ok=True)
            (publish_dir / "sources").mkdir(parents=True, exist_ok=True)
            digest = {
                "date": "2026-05-17",
                "summary": "Selected 1 RSS stories for today.",
                "highlights": ["Robot story"],
                "counts": {"wechat": 1, "x": 0, "arxiv": 0, "bilibili": 0, "rss": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 1,
                        "items": [
                            {
                                "id": "entry-1",
                                "title": "Robot story",
                                "summary": "Robot story",
                            }
                        ],
                    }
                ],
            }
            for target in [publish_dir / "latest.json", publish_dir / "daily" / "2026-05-17.json"]:
                target.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
            (publish_dir / "manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (publish_dir / "sources" / "wechat.json").write_text(json.dumps({"items": []}), encoding="utf-8")

            result = rss_verify.verify_paths(publish_dir, "2026-05-17")
            self.assertTrue(result["ok"])
            self.assertTrue(result["content_checks"]["ok"])
            self.assertEqual(result["content_checks"]["story_count"], 1)

    def test_verify_paths_fails_for_invalid_digest_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            publish_dir = root / "publish-out"
            (publish_dir / "daily").mkdir(parents=True, exist_ok=True)
            (publish_dir / "sources").mkdir(parents=True, exist_ok=True)
            invalid_digest = {
                "date": "2026-05-16",
                "summary": "bad",
                "highlights": [],
                "counts": {"wechat": 1},
                "stories": [
                    {
                        "story_id": "",
                        "title": "",
                        "summary": "",
                    }
                ],
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 1,
                        "items": [{}],
                    }
                ],
            }
            for target in [publish_dir / "latest.json", publish_dir / "daily" / "2026-05-17.json"]:
                target.write_text(json.dumps(invalid_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            (publish_dir / "manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (publish_dir / "sources" / "wechat.json").write_text(json.dumps({"items": []}), encoding="utf-8")

            result = rss_verify.verify_paths(publish_dir, "2026-05-17")
            self.assertFalse(result["ok"])
            self.assertFalse(result["content_checks"]["ok"])
            self.assertTrue(result["content_checks"]["issues"])

    def test_verify_paths_fails_when_section_counts_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            publish_dir = root / "publish-out"
            (publish_dir / "daily").mkdir(parents=True, exist_ok=True)
            (publish_dir / "sources").mkdir(parents=True, exist_ok=True)
            digest = {
                "date": "2026-05-17",
                "summary": "Selected 1 RSS stories for today.",
                "highlights": ["Robot story"],
                "counts": {"wechat": 5, "x": 0, "arxiv": 0, "bilibili": 0, "rss": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 3,
                        "items": [
                            {
                                "id": "entry-1",
                                "title": "Robot story",
                                "summary": "Robot story",
                            }
                        ],
                    }
                ],
            }
            for target in [publish_dir / "latest.json", publish_dir / "daily" / "2026-05-17.json"]:
                target.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
            (publish_dir / "manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (publish_dir / "sources" / "wechat.json").write_text(json.dumps({"items": []}), encoding="utf-8")

            result = rss_verify.verify_paths(publish_dir, "2026-05-17")
            self.assertFalse(result["ok"])
            self.assertFalse(result["content_checks"]["ok"])
            self.assertTrue(any("declared count does not match item count" in issue for issue in result["content_checks"]["issues"]))
            self.assertTrue(any("Counts mismatch for source" in issue for issue in result["content_checks"]["issues"]))


if __name__ == "__main__":
    unittest.main()
