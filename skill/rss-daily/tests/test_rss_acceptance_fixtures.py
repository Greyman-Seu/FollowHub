import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "skill" / "rss-daily" / "tests" / "fixtures"
RSS_DEDUPE_PATH = REPO_ROOT / "skill" / "rss-dedupe" / "rss_dedupe.py"
RSS_CLUSTER_PATH = REPO_ROOT / "skill" / "rss-cluster" / "rss_cluster.py"
RSS_DAILY_PATH = REPO_ROOT / "skill" / "rss-daily" / "run_daily.py"


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


rss_dedupe = load_module(RSS_DEDUPE_PATH, "rss_dedupe_fixture_module")
rss_cluster = load_module(RSS_CLUSTER_PATH, "rss_cluster_fixture_module")
rss_daily = load_module(RSS_DAILY_PATH, "rss_daily_fixture_module")


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class RssAcceptanceFixtureTests(unittest.TestCase):
    def test_same_wechat_mirror_fixture(self):
        fixture = load_fixture("rss_acceptance_same_wechat_mirror.json")
        deduped = rss_dedupe.dedupe_items(fixture["items"])
        self.assertEqual(deduped["item_count"], fixture["expected"]["deduped_item_count"])
        self.assertEqual(deduped["items"][0]["canonical_id"], fixture["expected"]["canonical_id"])

        clustered = rss_cluster.cluster_items(deduped["items"])
        self.assertEqual(clustered["story_count"], fixture["expected"]["story_count"])
        self.assertEqual(clustered["items"][0]["story_id"], fixture["expected"]["story_id"])
        self.assertEqual(clustered["stories"][0]["story_status"], fixture["expected"]["story_status"])
        self.assertEqual(clustered["stories"][0]["mention_count"], fixture["expected"]["mention_count"])

    def test_followup_same_story_fixture(self):
        fixture = load_fixture("rss_acceptance_followup_same_story.json")
        clustered = rss_cluster.cluster_items(fixture["items"])
        self.assertEqual(clustered["story_count"], fixture["expected"]["story_count"])
        status_by_id = {item["id"]: item["story_status"] for item in clustered["items"]}
        for item_id, expected_row in fixture["expected"]["items"].items():
            self.assertEqual(status_by_id[item_id], expected_row["story_status"])

    def test_recent_history_hint_fixture(self):
        fixture = load_fixture("rss_acceptance_recent_history_hint.json")
        history = {fixture["history"]["story_id"]: fixture["history"]}
        hint = rss_daily.build_history_hint(fixture["entry"], history)
        for key, value in fixture["expected"].items():
            self.assertEqual(hint[key], value)


if __name__ == "__main__":
    unittest.main()
