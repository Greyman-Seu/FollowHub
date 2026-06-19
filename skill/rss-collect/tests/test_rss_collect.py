import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_load_rss_settings_supports_collect_workers_and_proxy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                """
rss:
  daily:
    lookback_days: 3
    max_items_per_source: 12
  collect:
    max_workers: 5
    request_timeout_seconds: 18
  proxy:
    http: http://127.0.0.1:7890
    https: http://127.0.0.1:7890
""",
                encoding="utf-8",
            )
            settings = self.module.load_rss_settings(config_path)
        self.assertEqual(settings["lookback_days"], 3)
        self.assertEqual(settings["max_items_per_source"], 12)
        self.assertEqual(settings["max_workers"], 5)
        self.assertEqual(settings["request_timeout_seconds"], 18)
        self.assertEqual(settings["proxy_settings"]["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(settings["proxy_settings"]["HTTPS_PROXY"], "http://127.0.0.1:7890")

    def test_env_proxy_overrides_config_proxy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                """
rss:
  proxy:
    http: http://127.0.0.1:7890
""",
                encoding="utf-8",
            )
            old_http = os.environ.get("HTTP_PROXY")
            os.environ["HTTP_PROXY"] = "http://127.0.0.1:9999"
            try:
                settings = self.module.load_rss_settings(config_path)
            finally:
                if old_http is None:
                    os.environ.pop("HTTP_PROXY", None)
                else:
                    os.environ["HTTP_PROXY"] = old_http
        self.assertEqual(settings["proxy_settings"]["HTTP_PROXY"], "http://127.0.0.1:9999")

    def test_collect_policy_uses_conservative_settings_for_x_sources(self):
        settings = {
            "lookback_days": 2,
            "max_items_per_source": 50,
            "max_workers": 8,
            "request_timeout_seconds": 30,
            "proxy_settings": {},
        }
        src = self.module.SourceConfig(
            name="x-sama",
            source_type="x",
            feed_url="https://nitter.net/sama/rss",
        )
        policy = self.module.collect_policy(settings, src)
        self.assertEqual(policy["max_workers"], 4)
        self.assertEqual(policy["retry_count"], 1)
        self.assertGreaterEqual(policy["request_timeout_seconds"], 8)

    def test_collect_one_source_retries_retryable_timeout(self):
        src = self.module.SourceConfig(
            name="x-sama",
            source_type="x",
            feed_url="https://nitter.net/sama/rss",
        )
        calls = {"count": 0}

        def fake_collect_source_items(source, *, lookback_days, default_max_items, request_timeout_seconds):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("timed out")
            return [{"id": "x:1", "title": "ok"}]

        with patch.object(self.module, "collect_source_items", side_effect=fake_collect_source_items):
            items, stat = self.module.collect_one_source(
                src,
                lookback_days=2,
                default_max_items=10,
                request_timeout_seconds=20,
                proxy_settings={},
                retry_count=1,
                retry_backoff_seconds=0.0,
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(stat["status"], "ok")
        self.assertEqual(stat["attempts"], 2)

    def test_fetch_text_uses_curl_for_nitter_sources(self):
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout="<rss></rss>",
            stderr="",
        )
        with patch.object(self.module, "_requests", None):
            with patch.object(self.module.shutil, "which", return_value="/usr/bin/curl"):
                with patch.object(self.module.subprocess, "run", return_value=completed) as mocked_run:
                    text = self.module.fetch_text("https://nitter.net/sama/rss", timeout=12)
        self.assertEqual(text, "<rss></rss>")
        mocked_run.assert_called_once()

    def test_fetch_text_prefers_requests_for_nitter_sources(self):
        class Resp:
            status_code = 200
            text = "<rss></rss>"

            def raise_for_status(self):
                return None

        fake_requests = type("R", (), {"get": staticmethod(lambda url, timeout, headers: Resp())})
        with patch.object(self.module, "_requests", fake_requests):
            with patch.object(self.module.subprocess, "run") as mocked_run:
                text = self.module.fetch_text("https://nitter.net/sama/rss", timeout=12)
        self.assertEqual(text, "<rss></rss>")
        mocked_run.assert_not_called()

    def test_format_network_error_suggests_proxy_when_dns_fails(self):
        message = self.module.format_network_error(Exception("[Errno 8] nodename nor servname provided, or not known"), {})
        self.assertIn("HTTP_PROXY/HTTPS_PROXY", message)
        self.assertIn("先问用户", message)

    def test_format_network_error_explains_operation_not_permitted(self):
        message = self.module.format_network_error(Exception("[Errno 1] Operation not permitted"), {"HTTP_PROXY": "http://127.0.0.1:7890"})
        self.assertIn("当前 shell 进程无法直接连接网络或本地代理端口", message)

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
            self.assertEqual(payload["max_workers"], 8)

    def test_prune_stale_sources_classifies_stale_and_broken(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_path = tmp_path / "rss_sources.yaml"
            source_path.write_text(
                """# keep this header
sources:
  - name: fresh
    type: x
    feed_url: https://example.com/fresh.xml
  - name: stale
    type: x
    feed_url: https://example.com/stale.xml
  - name: broken
    type: x
    feed_url: https://example.com/broken.xml
""",
                encoding="utf-8",
            )

            def fake_fetch_text(url, timeout=30):
                if "fresh" in url:
                    return """<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Fresh</title><link>https://e/fresh</link><guid>fresh-1</guid><pubDate>Tue, 10 Jun 2026 09:00:00 GMT</pubDate><description>fresh</description></item></channel></rss>"""
                if "stale" in url:
                    return """<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Stale</title><link>https://e/stale</link><guid>stale-1</guid><pubDate>Tue, 10 Jun 2025 09:00:00 GMT</pubDate><description>stale</description></item></channel></rss>"""
                raise RuntimeError("network down")

            with patch.object(self.module, "fetch_text", side_effect=fake_fetch_text):
                with patch.object(
                    self.module,
                    "utc_now",
                    return_value=self.module.datetime(2026, 6, 17, 0, 0, tzinfo=self.module.timezone.utc),
                ):
                    report = self.module.prune_stale_sources(
                        source_file=source_path,
                        proxy_settings={},
                        stale_days=183,
                        request_timeout_seconds=20,
                        max_workers=2,
                        apply_changes=False,
                    )

            self.assertEqual(report["source_count_before"], 3)
            self.assertEqual(report["source_count_after"], 1)
            self.assertEqual(report["stale_count"], 1)
            self.assertEqual(report["broken_count"], 1)
            self.assertEqual(report["stale_sources"][0]["name"], "stale")
            self.assertEqual(report["broken_sources"][0]["name"], "broken")

    def test_prune_stale_sources_apply_rewrites_source_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_path = tmp_path / "rss_sources.yaml"
            source_path.write_text(
                """# header line
sources:
  - name: fresh
    type: x
    feed_url: https://example.com/fresh.xml
  - name: stale
    type: x
    feed_url: https://example.com/stale.xml
  - name: broken
    type: x
    feed_url: https://example.com/broken.xml
""",
                encoding="utf-8",
            )

            def fake_fetch_text(url, timeout=30):
                if "fresh" in url:
                    return """<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Fresh</title><link>https://e/fresh</link><guid>fresh-1</guid><pubDate>Tue, 10 Jun 2026 09:00:00 GMT</pubDate><description>fresh</description></item></channel></rss>"""
                if "stale" in url:
                    return """<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Stale</title><link>https://e/stale</link><guid>stale-1</guid><pubDate>Tue, 10 Jun 2025 09:00:00 GMT</pubDate><description>stale</description></item></channel></rss>"""
                raise RuntimeError("network down")

            with patch.object(self.module, "fetch_text", side_effect=fake_fetch_text):
                with patch.object(
                    self.module,
                    "utc_now",
                    return_value=self.module.datetime(2026, 6, 17, 0, 0, tzinfo=self.module.timezone.utc),
                ):
                    report = self.module.prune_stale_sources(
                        source_file=source_path,
                        proxy_settings={},
                        stale_days=183,
                        request_timeout_seconds=20,
                        max_workers=2,
                        apply_changes=True,
                    )

            self.assertEqual(report["source_count_before"], 3)
            self.assertEqual(report["source_count_after"], 1)
            saved = self.module.load_yaml(source_path)
            self.assertEqual(len(saved["sources"]), 1)
            self.assertEqual(saved["sources"][0]["name"], "fresh")
            self.assertTrue(source_path.read_text(encoding="utf-8").startswith("# header line"))


if __name__ == "__main__":
    unittest.main()
