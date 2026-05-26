import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skill" / "rss-collect" / "rss_collect.py"


def load_module():
    spec = importlib.util.spec_from_file_location("followhub_rss_collect", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RssCollectSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_load_sources_supports_sources_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            sources_path = tmp_path / "rss_sources.yaml"
            sources_path.write_text(
                """
sources:
  - name: test-wechat
    type: wechat
    feed_url: https://example.com/a.xml
""",
                encoding="utf-8",
            )
            config_path.write_text(
                """
rss:
  sources_file: rss_sources.yaml
""",
                encoding="utf-8",
            )
            sources = self.module.load_sources(config_path)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "test-wechat")

    def test_parse_rss_feed(self):
        xml_text = """<?xml version="1.0"?>
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
"""
        source = self.module.SourceConfig(name="example", source_type="wechat", feed_url="https://example.com/feed.xml")
        items = self.module.parse_feed(xml_text, source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Item One")
        self.assertEqual(items[0]["source_type"], "wechat")

    def test_cli_collect_with_local_feed(self):
        xml_text = """<?xml version="1.0"?>
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
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            feed_path = tmp_path / "feed.xml"
            config_path = tmp_path / "config.yaml"
            output_path = tmp_path / "output.json"
            feed_path.write_text(xml_text, encoding="utf-8")
            config_path.write_text(
                f"""
rss:
  daily:
    lookback_days: 4000
    max_items_per_source: 10
  sources:
    - name: example
      type: wechat
      feed_url: {feed_path.as_uri()}
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "collect",
                    "--config",
                    str(config_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["item_count"], 1)
            self.assertEqual(payload["items"][0]["title"], "Item One")


if __name__ == "__main__":
    unittest.main()
