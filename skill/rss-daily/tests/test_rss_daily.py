import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-daily" / "run_daily.py"


class RssDailySkillTests(unittest.TestCase):
    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("rss-daily", result.stdout)

    def test_daily_stops_when_prefilter_results_missing(self):
        config_text = """
rss:
  sources:
    - name: test-wechat
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Item One</title>
      <link>https://example.com/1</link>
      <guid>id-1</guid>
      <pubDate>Tue, 13 May 2026 09:00:00 GMT</pubDate>
      <description>Hello world</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-12",
                    "--output-root",
                    str(output_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("prefilter_results.json is missing", result.stderr + result.stdout)
            raw_path = collect_root / "2026-05-12-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_runs_end_to_end_with_local_feed(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 10
  sources:
    - name: test-wechat
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Agent release note</title>
      <link>https://example.com/agent-release</link>
      <guid>id-1</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>Agent workflow update with tool use.</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-18",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            self.assertTrue((output_root / "2026-05-18" / "publish-out" / "latest.json").exists())
            raw_path = collect_root / "2026-05-18-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_dedupes_same_wechat_article_into_one_story(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 10
  sources:
    - name: feed-a
      type: wechat
      feed_url: __FEED_A__
    - name: feed-b
      type: wechat
      feed_url: __FEED_B__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_a = tmp_path / "feed-a.xml"
            feed_b = tmp_path / "feed-b.xml"
            link = "https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz"
            feed_a.write_text(
                f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed A</title>
    <item>
      <title>WeChat Article</title>
      <link>{link}</link>
      <guid>a-1</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>First mirror</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            feed_b.write_text(
                f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed B</title>
    <item>
      <title>WeChat Article</title>
      <link>{link}&amp;utm_source=rss</link>
      <guid>b-1</guid>
      <pubDate>Sun, 17 May 2026 10:00:00 GMT</pubDate>
      <description>Second mirror</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(
                config_text.replace("__FEED_A__", feed_a.as_uri()).replace("__FEED_B__", feed_b.as_uri()),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-18",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            digest_path = output_root / "2026-05-18" / "daily-digest.json"
            digest = __import__("json").loads(digest_path.read_text(encoding="utf-8"))
            self.assertEqual(digest["sections"][0]["count"], 1)
            item = digest["sections"][0]["items"][0]
            self.assertEqual(item["mention_count"], 2)
            self.assertEqual(item["story_id"], "story:wechat:abc:123:1:xyz")
            raw_path = collect_root / "2026-05-18-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_filters_focus_and_ads_from_yaml(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
  keywords:
    - robot
    - robotics
    - llm
    - multimodal
    - video generation
    - image generation
    - diffusion
  exclude_keywords:
    - 广告
    - 课程
    - 招聘
    - sponsor
    - promotion
  topic_context: |
    关注机器人、视频/图像生成、大模型。排除广告、课程、招聘。
  sources:
    - name: mixed-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Mixed Feed</title>
    <item>
      <title>Robot manipulation policy update</title>
      <link>https://example.com/robot</link>
      <guid>robot-1</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>New robotics benchmark for manipulation.</description>
    </item>
    <item>
      <title>Multimodal LLM release</title>
      <link>https://example.com/llm</link>
      <guid>llm-1</guid>
      <pubDate>Sun, 17 May 2026 09:30:00 GMT</pubDate>
      <description>A new multimodal LLM with better reasoning.</description>
    </item>
    <item>
      <title>Video generation diffusion demo</title>
      <link>https://example.com/video</link>
      <guid>video-1</guid>
      <pubDate>Sun, 17 May 2026 10:00:00 GMT</pubDate>
      <description>Text-to-video generation and image generation updates.</description>
    </item>
    <item>
      <title>机器人课程广告</title>
      <link>https://example.com/ad-course</link>
      <guid>ad-1</guid>
      <pubDate>Sun, 17 May 2026 10:30:00 GMT</pubDate>
      <description>课程推广，限时报名优惠，广告。</description>
    </item>
    <item>
      <title>LLM 招聘信息</title>
      <link>https://example.com/job</link>
      <guid>job-1</guid>
      <pubDate>Sun, 17 May 2026 11:00:00 GMT</pubDate>
      <description>大模型团队招聘，欢迎投递。</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-18",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            digest_path = output_root / "2026-05-18" / "daily-digest.json"
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            items = []
            for section in digest["sections"]:
                items.extend(section["items"])
            titles = {item["title"] for item in items}
            self.assertIn("Robot manipulation policy update", titles)
            self.assertIn("Multimodal LLM release", titles)
            self.assertIn("Video generation diffusion demo", titles)
            self.assertNotIn("机器人课程广告", titles)
            self.assertNotIn("LLM 招聘信息", titles)
            raw_path = collect_root / "2026-05-18-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_keeps_only_target_date_items(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: dated-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Dated Feed</title>
    <item>
      <title>Robot item on target day</title>
      <link>https://example.com/robot-day</link>
      <guid>robot-day</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
    <item>
      <title>Robot item previous day</title>
      <link>https://example.com/robot-prev</link>
      <guid>robot-prev</guid>
      <pubDate>Sat, 16 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            raw_json = json.loads((collect_root / "2026-05-17-raw.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_json["item_count"], 1)
            self.assertEqual(raw_json["items"][0]["title"], "Robot item on target day")
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_drops_repeat_story_seen_in_previous_digest(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: repeated-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            previous_root = output_root / "2026-05-16"
            previous_root.mkdir(parents=True, exist_ok=True)
            previous_digest = {
                "date": "2026-05-16",
                "summary": "prev",
                "highlights": [],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 1,
                        "items": [
                            {
                                "id": "wechat:old",
                                "story_id": "story:wechat:abc:123:1:xyz",
                                "title": "Old robot story",
                                "summary": "old",
                            }
                        ],
                    }
                ],
            }
            (previous_root / "daily-digest.json").write_text(json.dumps(previous_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Repeated Feed</title>
    <item>
      <title>Robot repeat story</title>
      <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz</link>
      <guid>robot-repeat</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            digest_path = output_root / "2026-05-17" / "daily-digest.json"
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            total = sum(section["count"] for section in digest.get("sections", []))
            self.assertEqual(total, 0)
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_keeps_followup_story_seen_in_previous_digest(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
  strict_date_only: true
  keywords:
    - robot
    - launch
    - recap
  sources:
    - name: followup-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            previous_root = output_root / "2026-05-16"
            previous_root.mkdir(parents=True, exist_ok=True)
            previous_digest = {
                "date": "2026-05-16",
                "summary": "prev",
                "highlights": [],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0, "rss": 0},
                "stories": [
                    {
                        "story_id": "story:open-model-launch:2026-05-17",
                        "title": "Old launch story",
                        "summary": "old",
                    }
                ],
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "wechat",
                        "count": 1,
                        "items": [
                            {
                                "id": "wechat:old",
                                "story_id": "story:open-model-launch:2026-05-17",
                                "title": "Old launch story",
                                "summary": "old",
                            }
                        ],
                    }
                ],
            }
            (previous_root / "daily-digest.json").write_text(json.dumps(previous_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Followup Feed</title>
    <item>
      <title>Open model launch recap</title>
      <link>https://example.com/recap</link>
      <guid>launch-recap</guid>
      <pubDate>Sun, 17 May 2026 12:00:00 GMT</pubDate>
      <description>Open model launch recap with robot analysis and launch details.</description>
    </item>
    <item>
      <title>Open model launch details</title>
      <link>https://example.com/original</link>
      <guid>launch-original</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>Open model launch robot details.</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            digest_path = output_root / "2026-05-17" / "daily-digest.json"
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            total = sum(section["count"] for section in digest.get("sections", []))
            self.assertEqual(total, 1)
            story = digest["stories"][0]
            self.assertEqual(story["story_status"], "followup")
            self.assertEqual(story["story_id"], "story:open-model-launch:2026-05-17")
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_auto_workers_uses_recent_story_history_not_only_previous_day(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
    history_lookback_days: 7
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: repeated-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            older_root = output_root / "2026-05-14"
            older_root.mkdir(parents=True, exist_ok=True)
            older_digest = {
                "date": "2026-05-14",
                "summary": "older",
                "highlights": [],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0, "rss": 0},
                "stories": [
                    {
                        "story_id": "story:wechat:abc:123:1:xyz",
                        "story_status": "new",
                        "title": "Older robot story",
                        "source_types": ["wechat"],
                        "source_names": ["repeated-feed"],
                    }
                ],
                "sections": [],
            }
            (older_root / "daily-digest.json").write_text(json.dumps(older_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Repeated Feed</title>
    <item>
      <title>Robot repeat story</title>
      <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz</link>
      <guid>robot-repeat</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            history_path = output_root / "2026-05-17" / "story-history.json"
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(history["story_count"], 1)
            self.assertEqual(history["stories"][0]["story_id"], "story:wechat:abc:123:1:xyz")
            self.assertEqual(history["stories"][0]["source_types"], ["wechat"])
            self.assertEqual(history["stories"][0]["source_names"], ["repeated-feed"])
            self.assertEqual(history["stories"][0]["max_mention_count"], 0)
            digest_path = output_root / "2026-05-17" / "daily-digest.json"
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            total = sum(section["count"] for section in digest.get("sections", []))
            self.assertEqual(total, 0)
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_writes_recent_story_history_into_prefilter_and_filter_inputs(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
    history_lookback_days: 7
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: repeated-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            older_root = output_root / "2026-05-14"
            older_root.mkdir(parents=True, exist_ok=True)
            older_digest = {
                "date": "2026-05-14",
                "summary": "older",
                "highlights": [],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0, "rss": 0},
                "stories": [
                    {
                        "story_id": "story:wechat:abc:123:1:xyz",
                        "story_status": "new",
                        "title": "Older robot story",
                        "source_types": ["wechat"],
                        "source_names": ["repeated-feed"],
                        "mention_count": 2,
                    }
                ],
                "sections": [],
            }
            (older_root / "daily-digest.json").write_text(json.dumps(older_digest, ensure_ascii=False, indent=2), encoding="utf-8")
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Repeated Feed</title>
    <item>
      <title>Robot repeat story</title>
      <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz</link>
      <guid>robot-repeat</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            prefilter_input = json.loads((output_root / "2026-05-17" / "prefilter_input.json").read_text(encoding="utf-8"))
            filter_input = json.loads((output_root / "2026-05-17" / "filter_input.json").read_text(encoding="utf-8"))
            self.assertEqual(len(prefilter_input["recent_story_history"]), 1)
            self.assertEqual(prefilter_input["recent_story_history"][0]["story_id"], "story:wechat:abc:123:1:xyz")
            self.assertEqual(filter_input["recent_story_history"][0]["max_mention_count"], 2)
            self.assertIn("reviewer_prompt", prefilter_input)
            self.assertIn("reviewer_checklist", prefilter_input)
            self.assertIn("decision_criteria", prefilter_input)
            self.assertIn("reviewer_output_schema", prefilter_input)
            self.assertIn("reviewer_prompt", filter_input)
            self.assertIn("reviewer_checklist", filter_input)
            self.assertIn("decision_criteria", filter_input)
            self.assertIn("reviewer_output_schema", filter_input)
            self.assertTrue(prefilter_input["reviewer_checklist"])
            self.assertTrue(filter_input["reviewer_checklist"])
            self.assertEqual(prefilter_input["decision_criteria"]["keep"], "Clear in-scope new item or strong followup worth deeper review.")
            self.assertEqual(filter_input["reviewer_output_schema"]["items"][0]["include_in_digest"], "boolean")
            self.assertTrue(prefilter_input["entries"][0]["history_hint"]["seen_recently"])
            self.assertEqual(prefilter_input["entries"][0]["history_hint"]["current_story_status"], "new")
            self.assertEqual(filter_input["entries"][0]["history_hint"]["history_publish_count"], 0)
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_updates_persistent_story_ledger(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
    history_lookback_days: 7
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: ledger-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Ledger Feed</title>
    <item>
      <title>Robot ledger story</title>
      <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz</link>
      <guid>robot-ledger</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            ledger_path = output_root / "_state" / "story-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["story_count"], 1)
            self.assertEqual(ledger["stories"][0]["story_id"], "story:wechat:abc:123:1:xyz")
            self.assertEqual(ledger["stories"][0]["first_seen_date"], "2026-05-17")
            self.assertEqual(ledger["stories"][0]["last_seen_date"], "2026-05-17")
            self.assertEqual(ledger["stories"][0]["publish_count"], 1)
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()

    def test_daily_combines_ledger_and_recent_history_into_filter_context(self):
        config_text = """
rss:
  daily:
    lookback_days: 30
    max_items_per_source: 20
    history_lookback_days: 7
  strict_date_only: true
  keywords:
    - robot
  sources:
    - name: ledger-feed
      type: wechat
      feed_url: __FEED_URL__
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            output_root = tmp_path / "rss-daily-output"
            collect_root = REPO_ROOT / "rss-collect-output"
            state_root = output_root / "_state"
            state_root.mkdir(parents=True, exist_ok=True)
            ledger_payload = {
                "mode": "rss-story-ledger",
                "updated_at": "2026-05-16",
                "story_count": 1,
                "stories": [
                    {
                        "story_id": "story:ledger-only",
                        "first_seen_date": "2026-05-10",
                        "seen_dates": ["2026-05-10", "2026-05-16"],
                        "last_seen_date": "2026-05-16",
                        "latest_story_status": "new",
                        "latest_title": "Ledger only story",
                        "source_types": ["wechat"],
                        "source_names": ["ledger-feed"],
                        "max_mention_count": 3,
                        "publish_count": 2,
                    }
                ],
            }
            (state_root / "story-ledger.json").write_text(json.dumps(ledger_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            feed_path = tmp_path / "feed.xml"
            feed_path.write_text(
                """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Ledger Feed</title>
    <item>
      <title>Robot ledger story</title>
      <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1&amp;sn=xyz</link>
      <guid>robot-ledger</guid>
      <pubDate>Sun, 17 May 2026 09:00:00 GMT</pubDate>
      <description>robot update</description>
    </item>
  </channel>
</rss>
""",
                encoding="utf-8",
            )
            config_path.write_text(config_text.replace("__FEED_URL__", feed_path.as_uri()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "daily",
                    "--config",
                    str(config_path),
                    "--date",
                    "2026-05-17",
                    "--output-root",
                    str(output_root),
                    "--auto-workers",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            prefilter_input = json.loads((output_root / "2026-05-17" / "prefilter_input.json").read_text(encoding="utf-8"))
            story_ids = {item["story_id"] for item in prefilter_input["recent_story_history"]}
            self.assertIn("story:ledger-only", story_ids)
            ledger_only = next(item for item in prefilter_input["recent_story_history"] if item["story_id"] == "story:ledger-only")
            self.assertEqual(ledger_only["history_sources"], ["ledger"])
            history_hint = prefilter_input["entries"][0]["history_hint"]
            self.assertFalse(history_hint["history_source_overlap"])
            self.assertEqual(history_hint["history_publish_count"], 0)
            raw_path = collect_root / "2026-05-17-raw.json"
            if raw_path.exists():
                raw_path.unlink()


if __name__ == "__main__":
    unittest.main()
