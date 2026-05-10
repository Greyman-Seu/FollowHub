import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "paper-analyze"
SCRIPT_PATH = SKILL_DIR / "paper_analyze.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_paper_analyze", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PaperAnalyzeSkillTests(unittest.TestCase):
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
        self.assertIn("paper-analyze", result.stdout)

    def test_slugify(self):
        self.assertEqual(self.module.slugify("Test-Time Scaling for Robots"), "test-time-scaling-for-robots")

    def test_resolve_input_source_for_arxiv_id(self):
        original_fetch = self.module.maybe_fetch_url
        try:
            self.module.maybe_fetch_url = lambda url: (
                '<html><head><title>Sample Title | arXiv</title>'
                '<meta name="citation_date" content="2026-05-11" /></head>'
                '<blockquote class="abstract">Abstract: First sentence. Second sentence.</blockquote></html>'
            )
            source = self.module.resolve_input_source("2402.12345")
        finally:
            self.module.maybe_fetch_url = original_fetch
        self.assertEqual(source.source_kind, "arxiv_id")
        self.assertEqual(source.paper_id, "2402.12345")
        self.assertEqual(source.canonical_url, "https://arxiv.org/abs/2402.12345")
        self.assertEqual(source.title_hint, "Sample Title")
        self.assertEqual(source.abstract_text, "First sentence. Second sentence.")
        self.assertEqual(source.publish_date_hint, "2026-05-11")

    def test_resolve_input_source_for_local_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "My-Paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            source = self.module.resolve_input_source(str(pdf_path))
            self.assertEqual(source.source_kind, "local_pdf")
            self.assertEqual(source.local_path, pdf_path.resolve())
            self.assertEqual(source.title_hint, "My Paper")

    def test_resolve_input_source_for_local_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "paper.html"
            html_path.write_text(
                '<html><head><title>Example Paper | arXiv</title></head><body><a href="https://arxiv.org/abs/2501.12345">abs</a></body></html>',
                encoding="utf-8",
            )
            source = self.module.resolve_input_source(str(html_path))
            self.assertEqual(source.source_kind, "local_html")
            self.assertEqual(source.paper_id, "2501.12345")
            self.assertEqual(source.title_hint, "Example Paper")
            self.assertEqual(source.publish_date_hint, "")

    def test_resolve_input_source_for_online_pdf_url(self):
        original_fetch = self.module.maybe_fetch_url
        try:
            self.module.maybe_fetch_url = lambda url: "<html><head><title>Fetched Title | arXiv</title></head></html>"
            source = self.module.resolve_input_source("https://arxiv.org/pdf/2501.12345.pdf")
        finally:
            self.module.maybe_fetch_url = original_fetch
        self.assertEqual(source.source_kind, "online_pdf_url")
        self.assertEqual(source.canonical_url, "https://arxiv.org/abs/2501.12345")
        self.assertEqual(source.title_hint, "Fetched Title")

    def test_build_markdown_contains_expected_sections(self):
        markdown = self.module.build_markdown(
            title="Example Paper",
            source_kind="arxiv_id",
            source_input="1234.5678",
            source_url="https://arxiv.org/abs/1234.5678",
            publish_date="2026-05-10",
            domain="agent",
            tags=["paper", "agent"],
            image_urls=["https://example.com/fig1.png"],
            related_topics=["tool-use-workflows"],
            summary="This paper studies tool use.",
            research_problem="Current agents fail on long tasks.",
            core_method="The paper proposes a planner plus tool loop.",
            key_takeaways=["Tool loops need explicit state."],
            experimental_signals=["Outperforms baseline on long tasks."],
            strengths=["Clear system decomposition."],
            limitations=["Only tested in one benchmark."],
            critical_notes=["Worth linking to knowledge-base-as-agent-memory."],
        )
        self.assertIn("# Example Paper", markdown)
        self.assertIn("## Research Problem", markdown)
        self.assertIn("https://example.com/fig1.png", markdown)
        self.assertIn("tool-use-workflows", markdown)

    def test_derive_fields_from_text_prefers_abstract(self):
        fields = self.module.derive_fields_from_text(
            "Raw body first. Raw body second.",
            "Abstract one. Abstract two. Abstract three.",
        )
        self.assertEqual(fields["research_problem"], "Abstract one.")
        self.assertEqual(fields["core_method"], "Abstract two.")
        self.assertIn("Abstract three.", fields["summary"])

    def test_write_mode_uses_configured_wiki_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.yaml"
            wiki_root = root / "llm-wiki"
            config_path.write_text(
                "\n".join(
                    [
                        "wiki:",
                        f"  root: {wiki_root}",
                        "  sources_dir: wiki/sources",
                        "paper_analyze:",
                        "  output_mode: write",
                        f"  draft_dir: {root / 'drafts'}",
                        "  language: zh",
                        "  r2_base_url: https://cdn.example.com/wiki",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "write",
                    "--config",
                    str(config_path),
                    "--input",
                    "https://arxiv.org/abs/1234.5678",
                    "--title",
                    "Example Paper",
                    "--summary",
                    "One sentence summary.",
                    "--research-problem",
                    "A hard problem.",
                    "--core-method",
                    "A useful method.",
                    "--print-json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            output_path = Path(payload["output_path"])
            self.assertTrue(output_path.exists())
            self.assertTrue(str(output_path).startswith(str(wiki_root)))
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("# Example Paper", content)
            self.assertIn("One sentence summary.", content)

    def test_write_mode_uses_derived_fields_from_local_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.yaml"
            wiki_root = root / "llm-wiki"
            html_path = root / "paper.html"
            html_path.write_text(
                "<html><head><title>HTML Paper</title><meta name=\"citation_date\" content=\"2026-05-12\" /></head>"
                "<body><blockquote class=\"abstract\">Abstract: First abstract sentence. Second abstract sentence.</blockquote></body></html>",
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        "wiki:",
                        f"  root: {wiki_root}",
                        "  sources_dir: wiki/sources",
                    ]
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "write",
                    "--config",
                    str(config_path),
                    "--input",
                    str(html_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            written = next((wiki_root / "wiki" / "sources").glob("*.md"))
            content = written.read_text(encoding="utf-8")
            self.assertIn("First abstract sentence.", content)
            self.assertIn("2026-05-12", content)

    def test_draft_mode_uses_draft_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.yaml"
            draft_dir = root / "drafts"
            config_path.write_text(
                "\n".join(
                    [
                        "paper_analyze:",
                        "  output_mode: draft",
                        f"  draft_dir: {draft_dir}",
                    ]
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "draft",
                    "--config",
                    str(config_path),
                    "--input",
                    "https://example.com/papers/draft-paper.pdf",
                    "--title",
                    "Draft Paper",
                    "--summary",
                    "Short summary.",
                    "--print-json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            output_path = Path(payload["output_path"])
            self.assertTrue(output_path.exists())
            self.assertTrue(str(output_path).startswith(str(draft_dir)))


if __name__ == "__main__":
    unittest.main()
