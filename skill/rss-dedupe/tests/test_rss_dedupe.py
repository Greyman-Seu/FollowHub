import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-dedupe" / "rss_dedupe.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_dedupe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RssDedupeTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_dedupe_groups_same_wechat_article(self):
        items = [
            {
                "id": "wechat:1",
                "source_type": "wechat",
                "source_name": "a",
                "title": "Article",
                "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz&utm_source=rss",
                "published_at": "2026-05-18T10:00:00+00:00",
                "content_text": "short",
            },
            {
                "id": "wechat:2",
                "source_type": "wechat",
                "source_name": "b",
                "title": "Article",
                "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz",
                "published_at": "2026-05-18T11:00:00+00:00",
                "content_text": "longer content",
            },
        ]
        result = self.module.dedupe_items(items)
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["items"][0]["canonical_id"], "wechat:abc:123:1:xyz")
        self.assertEqual(result["items"][0]["duplicate_count"], 1)


if __name__ == "__main__":
    unittest.main()
