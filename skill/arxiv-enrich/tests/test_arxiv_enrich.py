import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-enrich"
SCRIPT_PATH = SKILL_DIR / "arxiv_enrich.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_enrich", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArxivEnrichSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_skill_files_exist(self):
        self.assertTrue(SKILL_PATH.exists())
        self.assertTrue(SCRIPT_PATH.exists())

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("arxiv-enrich", result.stdout)

    def test_enrich_entry_maps_summary_and_affiliations(self):
        entry = {
            "id": "2604.21924",
            "title": "Long-Horizon Manipulation via Trace-Conditioned VLA Planning",
            "summary": "Long-horizon manipulation remains challenging for vision-language-action policies.",
            "authors": ["Isabella Liu", "Sifei Liu"],
            "affiliations": ["Stanford University", "NVIDIA Research"],
            "summary_cn": "该工作把短程 VLA 执行扩展到长程操作规划。",
            "comments": "Project page: https://www.liuisabella.com/LoHoManip Code: https://github.com/example/loho",
            "relevance_score": 3.5,
        }
        enriched = self.module.enrich_entry(entry)

        self.assertEqual(enriched["abstract_en"], entry["summary"])
        self.assertEqual(enriched["first_affiliation"], "Stanford University")
        self.assertEqual(enriched["one_liner_zh"], "该工作把短程 VLA 执行扩展到长程操作规划。")
        self.assertTrue(enriched["code_urls"])
        self.assertTrue(enriched["project_urls"])
        self.assertFalse(enriched["needs_agent_summary"])
        self.assertEqual(enriched["agent_summary_prompt"], "")

    def test_enrich_entry_creates_empty_contract_fields_when_missing(self):
        entry = {
            "id": "2604.11111",
            "title": "Example",
            "summary": "A benchmark paper.",
        }
        enriched = self.module.enrich_entry(entry)

        self.assertEqual(enriched["summary_cn"], "")
        self.assertEqual(enriched["one_liner_zh"], "")
        self.assertEqual(enriched["first_affiliation"], "")
        self.assertEqual(enriched["code_urls"], [])
        self.assertEqual(enriched["project_urls"], [])
        self.assertEqual(enriched["citation_count"], 0)
        self.assertEqual(enriched["overall_score"], 0)
        self.assertTrue(enriched["needs_agent_summary"])
        self.assertIn("Example", enriched["agent_summary_prompt"])
        self.assertIn("A benchmark paper.", enriched["agent_summary_prompt"])
        self.assertIn("one_liner_zh", enriched["agent_summary_prompt"])
        self.assertIn("summary_cn", enriched["agent_summary_prompt"])

    def test_enrich_entry_calculates_quality_and_overall_score(self):
        entry = {
            "id": "2604.22222",
            "title": "A Novel Framework for Robot Policy Learning",
            "summary": "We propose a novel framework that achieves state-of-the-art accuracy on benchmark tasks.",
            "relevance_score": 3.0,
            "hot_score": 1.2,
        }
        enriched = self.module.enrich_entry(entry)

        self.assertGreater(enriched["quality_score"], 0)
        self.assertGreater(enriched["overall_score"], 0)

    def test_enrich_entry_derives_hot_score_from_citation_fields(self):
        entry = {
            "id": "2604.88888",
            "title": "Citation Example",
            "summary": "A cited paper.",
            "citationCount": 120,
            "influentialCitationCount": 8,
            "relevance_score": 1.0,
        }
        enriched = self.module.enrich_entry(entry)

        self.assertEqual(enriched["citation_count"], 120)
        self.assertEqual(enriched["influential_citation_count"], 8)
        self.assertGreater(enriched["hot_score"], 0)
        self.assertGreater(enriched["overall_score"], 0)

    def test_coerce_affiliations_splits_multiple_formats(self):
        affiliations = self.module._coerce_affiliations(
            "Tsinghua University ; Peking University | Shanghai AI Lab"
        )
        self.assertEqual(
            affiliations,
            ["Tsinghua University", "Peking University", "Shanghai AI Lab"],
        )

    def test_extract_affiliations_from_text_handles_cleanup(self):
        text = (
            "1 DepartmentofPoliticalSciences, Tsinghua University\n"
            "2 Microsoft Research Asia\n"
            "3 School of AI, Repub-\n"
            "lic of Korea University\n"
            "https://example.com should be ignored\n"
        )
        affiliations = self.module.extract_affiliations_from_text(text)
        self.assertIn("Department of Political Sciences, Tsinghua University", affiliations)
        self.assertIn("Microsoft Research Asia", affiliations)
        self.assertIn("School of AI, Republic of Korea University", affiliations)

    def test_enrich_payload_preserves_daily_mode(self):
        payload = {
            "mode": "daily",
            "date": "2026-04-24",
            "count": 1,
            "entries": [
                {
                    "id": "2604.33333",
                    "title": "Daily Paper",
                    "summary": "A robotics paper.",
                    "relevance_score": 1.5,
                }
            ],
        }
        enriched = self.module.enrich_payload(payload)
        self.assertEqual(enriched["mode"], "daily")
        self.assertIn("abstract_en", enriched["entries"][0])

    def test_build_payload_from_ids_uses_fetched_entries(self):
        original = self.module.fetch_entries_by_ids
        try:
            self.module.fetch_entries_by_ids = lambda ids: [
                {
                    "id": "2604.77777",
                    "title": "Fetched by ID",
                    "summary": "A fetched paper.",
                    "authors": ["A"],
                    "categories": ["cs.RO"],
                    "published": "2026-04-29T10:00:00Z",
                    "updated": "2026-04-29T10:00:00Z",
                    "pdf_url": "https://arxiv.org/pdf/2604.77777v1",
                    "html_url": "https://arxiv.org/abs/2604.77777v1",
                }
            ]
            payload = self.module.build_payload_from_ids(["2604.77777"])
        finally:
            self.module.fetch_entries_by_ids = original

        self.assertEqual(payload["mode"], "search")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][0]["id"], "2604.77777")

    def test_enrich_entry_uses_semantic_scholar_metadata_when_present(self):
        entry = {
            "id": "2604.12121",
            "title": "Semantic Scholar Example",
            "summary": "",
            "semantic_scholar": {
                "abstract": "Semantic Scholar abstract.",
                "citationCount": 50,
                "influentialCitationCount": 6,
                "authors": [
                    {"affiliations": [{"name": "Stanford University"}]},
                    {"affiliations": [{"name": "Google DeepMind"}]},
                ],
            },
            "relevance_score": 2.0,
        }
        enriched = self.module.enrich_entry(entry)

        self.assertEqual(enriched["abstract_en"], "Semantic Scholar abstract.")
        self.assertEqual(enriched["citation_count"], 50)
        self.assertEqual(enriched["influential_citation_count"], 6)
        self.assertEqual(enriched["first_affiliation"], "Stanford University")
        self.assertIn("Google DeepMind", enriched["affiliations"])

    def test_enrich_entry_uses_local_html_and_pdf_text_for_link_extraction(self):
        entry = {
            "id": "2604.13131",
            "title": "Link Enrichment Example",
            "summary": "A robotics paper.",
            "html_text": "Project page: https://example.ai/robot-policy",
            "pdf_head_text": "Code: https://github.com/example/robot-policy",
        }
        enriched = self.module.enrich_entry(entry)

        self.assertIn("https://example.ai/robot-policy", enriched["project_urls"])
        self.assertIn("https://github.com/example/robot-policy", enriched["code_urls"])

    def test_enrich_entry_fetches_semantic_scholar_when_enabled(self):
        original_fetch = self.module.fetch_semantic_scholar_metadata
        try:
            self.module.fetch_semantic_scholar_metadata = lambda **kwargs: {
                "abstract": "Fetched abstract from Semantic Scholar.",
                "citationCount": 33,
                "influentialCitationCount": 5,
                "authors": [
                    {"affiliations": [{"name": "CMU"}]},
                    {"affiliations": [{"name": "Google Research"}]},
                ],
            }
            entry = {
                "id": "2604.14141",
                "title": "External Metadata Example",
                "summary": "",
                "relevance_score": 1.5,
            }
            enriched = self.module.enrich_entry(
                entry,
                enable_external_metadata=True,
                semantic_scholar_api_key="dummy",
            )
        finally:
            self.module.fetch_semantic_scholar_metadata = original_fetch

        self.assertEqual(enriched["abstract_en"], "Fetched abstract from Semantic Scholar.")
        self.assertEqual(enriched["citation_count"], 33)
        self.assertEqual(enriched["influential_citation_count"], 5)
        self.assertEqual(enriched["first_affiliation"], "CMU")
        self.assertIn("Google Research", enriched["affiliations"])

    def test_enrich_entry_skips_external_fetch_without_api_key(self):
        original_fetch = self.module.fetch_semantic_scholar_metadata
        calls = []
        try:
            def fake_fetch(**kwargs):
                calls.append(kwargs)
                return {}
            self.module.fetch_semantic_scholar_metadata = fake_fetch
            entry = {
                "id": "2604.15151",
                "title": "No API Key Example",
                "summary": "A local-only paper.",
            }
            enriched = self.module.enrich_entry(
                entry,
                enable_external_metadata=True,
                semantic_scholar_api_key="",
            )
        finally:
            self.module.fetch_semantic_scholar_metadata = original_fetch

        self.assertEqual(calls, [])
        self.assertEqual(enriched["abstract_en"], "A local-only paper.")

    def test_cli_enriches_json_file(self):
        payload = {
            "mode": "search",
            "count": 1,
            "query": "robot policy",
            "entries": [
                {
                    "id": "2604.44444",
                    "title": "CLI Example",
                    "summary": "A robot policy paper with code.",
                    "comments": "https://github.com/example/cli-paper",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(self.module.json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "enrich",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            enriched = self.module.json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("abstract_en", enriched["entries"][0])
            self.assertTrue(enriched["entries"][0]["code_urls"])

    def test_main_enriches_ids_argument(self):
        original = self.module.fetch_entries_by_ids
        try:
            self.module.fetch_entries_by_ids = lambda ids: [
                {
                    "id": ids[0],
                    "title": "Fetched by CLI IDs",
                    "summary": "A fetched paper for CLI ids.",
                    "authors": ["CLI"],
                    "categories": ["cs.RO"],
                    "published": "2026-04-29T10:00:00Z",
                    "updated": "2026-04-29T10:00:00Z",
                    "pdf_url": f"https://arxiv.org/pdf/{ids[0]}v1",
                    "html_url": f"https://arxiv.org/abs/{ids[0]}v1",
                }
            ]
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.json"
                result = self.module.main(
                    [
                        "enrich",
                        "--ids",
                        "2604.66666",
                        "--output",
                        str(output_path),
                    ]
                )
                self.assertEqual(result, 0)
                enriched = self.module.json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(enriched["entries"][0]["id"], "2604.66666")
                self.assertIn("abstract_en", enriched["entries"][0])
        finally:
            self.module.fetch_entries_by_ids = original

    def test_summary_prompt_not_required_when_both_fields_present(self):
        entry = {
            "id": "2604.12345",
            "title": "Complete Summary Example",
            "summary": "An abstract.",
            "one_liner_zh": "一句话总结已存在。",
            "summary_cn": "中文总结也已经存在。",
        }
        enriched = self.module.enrich_entry(entry)
        self.assertFalse(enriched["needs_agent_summary"])
        self.assertEqual(enriched["agent_summary_prompt"], "")

    def test_resolve_semantic_scholar_api_key_prefers_argument_then_env(self):
        original_env = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        try:
            os.environ["SEMANTIC_SCHOLAR_API_KEY"] = "env-key"
            self.assertEqual(self.module.resolve_semantic_scholar_api_key("cli-key"), "cli-key")
            self.assertEqual(self.module.resolve_semantic_scholar_api_key(None), "env-key")
        finally:
            if original_env is None:
                os.environ.pop("SEMANTIC_SCHOLAR_API_KEY", None)
            else:
                os.environ["SEMANTIC_SCHOLAR_API_KEY"] = original_env


if __name__ == "__main__":
    unittest.main()
