import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-find"
SCRIPT_PATH = SKILL_DIR / "arxiv_find.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"
PROFILE_EXAMPLE_PATH = SKILL_DIR / "arxiv_profile.example.yaml"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_find", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArxivFindSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_skill_files_exist(self):
        self.assertTrue(SKILL_PATH.exists())
        self.assertTrue(SCRIPT_PATH.exists())
        self.assertTrue(PROFILE_EXAMPLE_PATH.exists())

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("arxiv-find", result.stdout)
        self.assertIn("daily", result.stdout)
        self.assertIn("backfill", result.stdout)
        self.assertIn("search", result.stdout)

    def test_load_profile_applies_shared_defaults(self):
        profile_yaml = textwrap.dedent(
            """
            categories:
              - cs.RO
            keywords:
              - vision-language-action
            favorites:
              enabled: true
              keywords:
                - VLA
              ignore_keywords:
                - Medical
            topic_context: |
              Real robot manipulation and VLA training recipes.
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.yaml"
            profile_path.write_text(profile_yaml, encoding="utf-8")
            profile = self.module.load_profile(profile_path)

        self.assertEqual(profile.categories, ["cs.RO"])
        self.assertEqual(profile.keywords, ["vision-language-action"])
        self.assertTrue(profile.favorites.enabled)
        self.assertEqual(profile.favorites.keywords, ["VLA"])
        self.assertEqual(profile.favorites.ignore_keywords, ["Medical"])
        self.assertTrue(profile.daily.new_submissions_only)
        self.assertTrue(profile.backfill.generate_overview)
        self.assertEqual(profile.logic, "AND")
        self.assertIn("Real robot manipulation", profile.topic_context)

    def test_parse_new_list_page_extracts_only_new_submissions(self):
        html = textwrap.dedent(
            """
            <html>
              <body>
                <h1>Computer Science</h1>
                <p>Showing new listings for Monday, 27 April 2026</p>
                <h3>New submissions (showing 2 of 2 entries)</h3>
                <dl id="new-submissions">
                  <dt><a href="/abs/2604.00001v1" title="Abstract">arXiv:2604.00001</a></dt>
                  <dd>Paper one</dd>
                  <dt><a href="/abs/2604.00002v2" title="Abstract">arXiv:2604.00002</a></dt>
                  <dd>Paper two</dd>
                </dl>
                <h3>Cross submissions (showing 1 of 1 entries)</h3>
                <dl id="cross-submissions">
                  <dt><a href="/abs/2604.00077v1" title="Abstract">arXiv:2604.00077</a></dt>
                  <dd>Cross paper</dd>
                </dl>
                <h3>Replacement submissions (showing 1 of 1 entries)</h3>
                <dl id="replacement-submissions">
                  <dt><a href="/abs/2604.00088v3" title="Abstract">arXiv:2604.00088</a></dt>
                  <dd>Replacement paper</dd>
                </dl>
              </body>
            </html>
            """
        )
        parsed = self.module.parse_new_list_page(html)

        self.assertEqual(parsed.listing_date, date(2026, 4, 27))
        self.assertEqual(parsed.new_submission_ids, ["2604.00001", "2604.00002"])
        self.assertEqual(parsed.section_counts["new"], 2)
        self.assertEqual(parsed.section_counts["cross"], 1)
        self.assertEqual(parsed.section_counts["replacement"], 1)

    def test_parse_new_list_page_handles_real_arxiv_structure(self):
        html = textwrap.dedent(
            """
            <div id='dlpage'>
              <h1>Robotics</h1>
              <h3>Showing new listings for Friday, 24 April 2026</h3>
              <dl id='articles'>
                <h3>New submissions (showing 2 of 2 entries)</h3>
                <dt>
                  <a name='item1'>[1]</a>
                  <a href ="/abs/2604.20893" title="Abstract" id="2604.20893">
                    arXiv:2604.20893
                  </a>
                </dt>
                <dd>Paper one</dd>
                <dt>
                  <a name='item2'>[2]</a>
                  <a href ="/abs/2604.20894v2" title="Abstract" id="2604.20894">
                    arXiv:2604.20894
                  </a>
                </dt>
                <dd>Paper two</dd>
                <h3>Cross-lists (showing 1 of 1 entries)</h3>
                <dt>
                  <a href ="/abs/2604.29999" title="Abstract" id="2604.29999">arXiv:2604.29999</a>
                </dt>
                <dd>Cross paper</dd>
                <h3>Replacements (showing 1 of 1 entries)</h3>
                <dt>
                  <a href ="/abs/2604.18888v3" title="Abstract" id="2604.18888">arXiv:2604.18888</a>
                </dt>
                <dd>Replacement paper</dd>
              </dl>
            </div>
            """
        )
        parsed = self.module.parse_new_list_page(html)

        self.assertEqual(parsed.listing_date, date(2026, 4, 24))
        self.assertEqual(parsed.new_submission_ids, ["2604.20893", "2604.20894"])

    def test_build_api_query_supports_keywords_categories_and_excludes(self):
        query = self.module.build_api_query(
            categories=["cs.RO", "cs.AI"],
            keywords=["vision-language-action", "robot policy"],
            exclude_keywords=["survey"],
            logic="AND",
        )

        self.assertIn("cat:cs.RO", query)
        self.assertIn("cat:cs.AI", query)
        self.assertIn("ti:\"vision-language-action\"", query)
        self.assertIn("abs:\"robot policy\"", query)
        self.assertIn("AND NOT", query)
        self.assertIn("survey", query)

    def test_plan_backfill_dates_is_inclusive_and_daily(self):
        dates = self.module.plan_backfill_dates("2026-04-24", "2026-04-27")
        self.assertEqual(
            dates,
            [
                date(2026, 4, 24),
                date(2026, 4, 25),
                date(2026, 4, 26),
                date(2026, 4, 27),
            ],
        )

    def test_render_backfill_overview_keeps_days_separate(self):
        daily_runs = [
            {
                "date": "2026-04-24",
                "count": 2,
                "output_markdown": "2026-04-24-daily.md",
            },
            {
                "date": "2026-04-25",
                "count": 1,
                "output_markdown": "2026-04-25-daily.md",
            },
        ]
        overview = self.module.render_backfill_overview_markdown(
            daily_runs=daily_runs,
            date_from="2026-04-24",
            date_to="2026-04-25",
        )

        self.assertIn("Backfill Overview", overview)
        self.assertIn("2026-04-24", overview)
        self.assertIn("2026-04-25", overview)
        self.assertIn("2026-04-24-daily.md", overview)
        self.assertIn("2026-04-25-daily.md", overview)
        self.assertIn("Total days: 2", overview)

    def test_skill_doc_records_requirements_and_design_boundary(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Requirements Snapshot", content)
        self.assertIn("Design Pattern", content)
        self.assertIn("New submissions", content)
        self.assertIn("arxiv-view", content)
        self.assertIn("favorites", content)

    def test_example_profile_includes_arxivreader_style_favorites(self):
        content = PROFILE_EXAMPLE_PATH.read_text(encoding="utf-8")
        self.assertIn("favorites:", content)
        self.assertIn("enabled: true", content)
        self.assertIn("- \"VLA\"", content)


if __name__ == "__main__":
    unittest.main()
