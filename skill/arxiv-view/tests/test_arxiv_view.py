import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-view"
SCRIPT_PATH = SKILL_DIR / "arxiv_view.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"
FIXTURES_DIR = SKILL_DIR / "tests" / "fixtures"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_view", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArxivViewSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_skill_files_exist(self):
        self.assertTrue(SKILL_PATH.exists())
        self.assertTrue(SCRIPT_PATH.exists())
        self.assertTrue((SKILL_DIR / "view_template" / "index.html").exists())
        self.assertTrue((SKILL_DIR / "view_template" / "app.js").exists())
        self.assertTrue((SKILL_DIR / "view_template" / "styles.css").exists())

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("arxiv-view", result.stdout)
        self.assertIn("build", result.stdout)

    def test_load_input_detects_daily_json(self):
        loaded = self.module.load_input(FIXTURES_DIR / "daily.json")
        self.assertEqual(loaded["kind"], "daily")
        self.assertEqual(loaded["payload"]["mode"], "daily")

    def test_load_input_detects_search_json(self):
        loaded = self.module.load_input(FIXTURES_DIR / "search.json")
        self.assertEqual(loaded["kind"], "search")
        self.assertEqual(loaded["payload"]["mode"], "search")

    def test_load_input_detects_backfill_overview_and_daily_files(self):
        loaded = self.module.load_input(FIXTURES_DIR / "backfill-overview.md")
        self.assertEqual(loaded["kind"], "backfill")
        self.assertEqual(len(loaded["daily_files"]), 2)
        self.assertTrue(str(loaded["daily_files"][0]).endswith("2026-04-24-daily.json"))
        self.assertTrue(str(loaded["daily_files"][1]).endswith("2026-04-25-daily.json"))

    def test_normalize_backfill_preserves_source_day(self):
        loaded = self.module.load_input(FIXTURES_DIR / "backfill-overview.md")
        normalized = self.module.normalize_loaded_input(loaded)
        self.assertEqual(normalized["mode"], "backfill")
        self.assertEqual(normalized["meta"]["day_count"], 2)
        self.assertEqual(normalized["meta"]["item_count"], 3)
        source_days = {item["source_day"] for item in normalized["items"]}
        self.assertEqual(source_days, {"2026-04-24", "2026-04-25"})

    def test_normalize_daily_maps_enrich_fields_and_abstract_fallback(self):
        loaded = self.module.load_input(FIXTURES_DIR / "daily.json")
        normalized = self.module.normalize_loaded_input(loaded)
        first = normalized["items"][0]
        second = normalized["items"][1]

        self.assertEqual(first["abstract_en"], "A VLA planning system for long-horizon manipulation.")
        self.assertEqual(first["one_liner_zh"], "把短视 VLA 执行扩展到长程操作规划。")
        self.assertEqual(first["summary_cn"], "该工作提出一个任务管理 VLM 与执行器解耦的长程操作框架。")
        self.assertEqual(first["first_affiliation"], "Stanford University")
        self.assertEqual(first["affiliations"][0], "Stanford University")
        self.assertEqual(first["hot_score"], 2.4)
        self.assertEqual(first["overall_score"], 4.6)
        self.assertTrue(first["code_urls"])
        self.assertTrue(first["project_urls"])

        self.assertEqual(second["abstract_en"], "Generative action head with explicit spatial anchors for VLA models.")
        self.assertEqual(second["one_liner_zh"], "")
        self.assertEqual(second["summary_cn"], "")
        self.assertEqual(second["first_affiliation"], "")

    def test_build_bundle_writes_static_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.module.build_bundle(
                input_path=FIXTURES_DIR / "daily.json",
                output_dir=Path(tmpdir),
            )
            self.assertTrue((Path(tmpdir) / "index.html").exists())
            self.assertTrue((Path(tmpdir) / "app.js").exists())
            self.assertTrue((Path(tmpdir) / "styles.css").exists())
            self.assertTrue((Path(tmpdir) / "data.json").exists())
            self.assertEqual(result["mode"], "daily")

    def test_generated_bundle_contains_favorites_and_clipboard_controls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_bundle(
                input_path=FIXTURES_DIR / "search.json",
                output_dir=Path(tmpdir),
            )
            html_text = (Path(tmpdir) / "index.html").read_text(encoding="utf-8")
            js_text = (Path(tmpdir) / "app.js").read_text(encoding="utf-8")
            self.assertIn("favoriteOnly", html_text)
            self.assertIn("copyFavorites", html_text)
            self.assertIn("navigator.clipboard", js_text)
            self.assertIn("localStorage", js_text)

    def test_generated_bundle_contains_enrich_display_slots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_bundle(
                input_path=FIXTURES_DIR / "daily.json",
                output_dir=Path(tmpdir),
            )
            html_text = (Path(tmpdir) / "index.html").read_text(encoding="utf-8")
            js_text = (Path(tmpdir) / "app.js").read_text(encoding="utf-8")
            self.assertIn("oneLiner", html_text)
            self.assertIn("summaryCn", html_text)
            self.assertIn("abstractDetails", html_text)
            self.assertIn("firstAffiliation", html_text)
            self.assertIn("hotness", html_text)
            self.assertIn("暂无中文总结", js_text)

    def test_data_json_contains_unified_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_bundle(
                input_path=FIXTURES_DIR / "backfill-overview.md",
                output_dir=Path(tmpdir),
            )
            payload = json.loads((Path(tmpdir) / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "backfill")
            self.assertEqual(len(payload["items"]), 3)
            self.assertIn("source_day", payload["items"][0])

    def test_invalid_input_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "bad.json"
            bad_path.write_text('{"hello":"world"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                self.module.load_input(bad_path)


if __name__ == "__main__":
    unittest.main()
