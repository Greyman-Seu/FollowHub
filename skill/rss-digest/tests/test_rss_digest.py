import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "skill" / "rss-digest" / "rss_digest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rss_digest_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


rss_digest = load_module()


class RssDigestTests(unittest.TestCase):
    def test_build_digest_emits_story_first_contract_and_sections(self):
        digest = rss_digest.build_digest(
            [
                {
                    "id": "entry-2",
                    "story_id": "story:wechat:abc:123:1:xyz",
                    "story_status": "new",
                    "source_type": "wechat",
                    "source_name": "feed-b",
                    "title": "Robot policy update",
                    "one_liner_zh": "机器人策略更新。",
                    "summary_cn": "这是对机器人策略更新的中文摘要。",
                    "url": "https://example.com/2",
                    "published_at": "2026-05-17T10:00:00Z",
                    "canonical_id": "wechat:abc:123:1:xyz",
                    "duplicate_count": 1,
                    "duplicate_items": [
                        {
                            "id": "entry-1",
                            "source_name": "feed-a",
                            "source_type": "wechat",
                            "url": "https://example.com/1",
                            "published_at": "2026-05-17T09:00:00Z",
                        }
                    ],
                    "domains": [{"slug": "agent", "name": "Agent"}],
                    "related_organizations": ["Stanford University"],
                    "related_companies": ["OpenAI"],
                    "key_people": ["Sergey Levine"],
                    "include_in_digest": True,
                },
                {
                    "id": "entry-3",
                    "story_id": "story:wechat:abc:123:1:xyz",
                    "story_status": "new",
                    "source_type": "wechat",
                    "source_name": "feed-c",
                    "title": "Robot policy update repost",
                    "one_liner_zh": "",
                    "summary_cn": "",
                    "url": "https://example.com/3",
                    "published_at": "2026-05-17T11:00:00Z",
                    "canonical_id": "wechat:abc:123:1:xyz",
                    "duplicate_count": 0,
                    "duplicate_items": [],
                    "domains": [{"slug": "agent", "name": "Agent"}],
                    "include_in_digest": True,
                },
            ]
        )

        self.assertIn("stories", digest)
        self.assertIn("sections", digest)
        self.assertEqual(len(digest["stories"]), 1)
        story = digest["stories"][0]
        self.assertEqual(story["story_id"], "story:wechat:abc:123:1:xyz")
        self.assertEqual(story["representative_item_id"], "entry-2")
        self.assertEqual(story["first_seen_at"], "2026-05-17T10:00:00Z")
        self.assertEqual(story["last_seen_at"], "2026-05-17T11:00:00Z")
        self.assertEqual(story["source_types"], ["wechat"])
        self.assertEqual(story["source_names"], ["feed-b", "feed-c"])
        self.assertEqual(story["mention_count"], 3)
        self.assertEqual(story["summary"], "机器人策略更新。")
        self.assertEqual(story["related_organizations"], ["Stanford University"])
        self.assertEqual(story["related_companies"], ["OpenAI"])
        self.assertEqual(story["key_people"], ["Sergey Levine"])
        self.assertEqual(len(digest["sections"]), 1)
        self.assertEqual(digest["sections"][0]["count"], 1)

    def test_build_digest_counts_rss_source_type(self):
        digest = rss_digest.build_digest(
            [
                {
                    "id": "entry-rss-1",
                    "story_id": "story:item:entry-rss-1",
                    "story_status": "new",
                    "source_type": "rss",
                    "source_name": "generic-feed",
                    "title": "Generic RSS item",
                    "one_liner_zh": "通用 RSS 条目。",
                    "summary_cn": "通用 RSS 条目的摘要。",
                    "url": "https://example.com/rss-1",
                    "published_at": "2026-05-17T08:00:00Z",
                    "canonical_id": "url:https://example.com/rss-1",
                    "duplicate_count": 0,
                    "duplicate_items": [],
                    "domains": [],
                    "include_in_digest": True,
                }
            ]
        )

        self.assertEqual(digest["counts"]["rss"], 1)
        self.assertEqual(len(digest["stories"]), 1)

    def test_build_digest_keeps_only_one_cn_summary_for_x(self):
        digest = rss_digest.build_digest(
            [
                {
                    "id": "x:1",
                    "story_id": "story:x:1",
                    "story_status": "new",
                    "source_type": "x",
                    "source_name": "x-sama",
                    "title": "Whoah. I did not realize AI had superhuman persuasion already.",
                    "one_liner_zh": "讨论了 AI 说服能力及其潜在社会影响。",
                    "summary_cn": "讨论了 AI 说服能力及其潜在社会影响。",
                    "url": "https://nitter.net/sama/status/1#m",
                    "published_at": "2026-06-18T08:00:00Z",
                    "canonical_id": "x:1",
                    "duplicate_count": 0,
                    "duplicate_items": [],
                    "domains": [],
                    "include_in_digest": True,
                }
            ]
        )

        story = digest["stories"][0]
        self.assertEqual(story["summary"], "讨论了 AI 说服能力及其潜在社会影响。")
        self.assertEqual(story["one_liner_zh"], "讨论了 AI 说服能力及其潜在社会影响。")
        self.assertEqual(story["summary_cn"], "")


if __name__ == "__main__":
    unittest.main()
