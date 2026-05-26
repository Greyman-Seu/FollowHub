import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-cluster" / "rss_cluster.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_cluster", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RssClusterTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_cluster_uses_canonical_id_as_story_anchor(self):
        items = [
            {
                "id": "x:1",
                "canonical_id": "x-status:123",
                "source_type": "x",
                "source_name": "feed-a",
                "title": "New agent release thread",
                "published_at": "2026-05-18T09:00:00+00:00",
                "content_text": "agent release details",
                "duplicate_count": 0,
            }
        ]
        result = self.module.cluster_items(items)
        self.assertEqual(result["story_count"], 1)
        self.assertEqual(result["items"][0]["story_id"], "story:x-status:123")
        self.assertEqual(result["items"][0]["story_status"], "new")

    def test_cluster_marks_duplicates_as_repeat_and_builds_story_index(self):
        items = [
            {
                "id": "wechat:1",
                "canonical_id": "wechat:abc:123:1:xyz",
                "source_type": "wechat",
                "source_name": "feed-a",
                "title": "Robot policy update",
                "published_at": "2026-05-18T09:00:00+00:00",
                "content_text": "robot policy details",
                "duplicate_count": 1,
            },
            {
                "id": "wechat:2",
                "canonical_id": "wechat:abc:123:1:xyz",
                "source_type": "wechat",
                "source_name": "feed-b",
                "title": "Robot policy update repost",
                "published_at": "2026-05-18T10:00:00+00:00",
                "content_text": "more robot policy details",
                "duplicate_count": 0,
            },
        ]
        result = self.module.cluster_items(items)
        self.assertEqual(result["story_count"], 1)
        self.assertEqual(result["items"][0]["story_id"], "story:wechat:abc:123:1:xyz")
        self.assertEqual(result["items"][0]["story_status"], "repeat")
        self.assertEqual(result["stories"][0]["story_id"], "story:wechat:abc:123:1:xyz")
        self.assertEqual(result["stories"][0]["source_types"], ["wechat"])
        self.assertEqual(result["stories"][0]["source_names"], ["feed-a", "feed-b"])
        self.assertEqual(result["stories"][0]["first_seen_at"], "2026-05-18T09:00:00+00:00")
        self.assertEqual(result["stories"][0]["last_seen_at"], "2026-05-18T10:00:00+00:00")
        self.assertEqual(result["stories"][0]["mention_count"], 2)
        self.assertEqual(result["stories"][0]["story_status"], "new")

    def test_cluster_marks_distinct_canonical_items_in_same_story_as_followup(self):
        items = [
            {
                "id": "story:1",
                "canonical_id": "url:https://example.com/original",
                "source_type": "x",
                "source_name": "feed-a",
                "title": "Open model launch details",
                "published_at": "2026-05-18T09:00:00+00:00",
                "content_text": "Open model launch details from official account",
                "duplicate_count": 0,
            },
            {
                "id": "story:2",
                "canonical_id": "url:https://example.com/recap",
                "source_type": "wechat",
                "source_name": "feed-b",
                "title": "Open model launch recap",
                "published_at": "2026-05-18T12:00:00+00:00",
                "content_text": "Open model launch details and recap analysis",
                "duplicate_count": 0,
            },
        ]
        result = self.module.cluster_items(items)
        self.assertEqual(result["story_count"], 1)
        self.assertEqual(result["items"][0]["story_status"], "new")
        self.assertEqual(result["items"][1]["story_status"], "followup")
        self.assertEqual(result["stories"][0]["story_id"], result["items"][0]["story_id"])


if __name__ == "__main__":
    unittest.main()
