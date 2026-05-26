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

    def test_maybe_extract_figure_urls_prefers_arxiv_when_paper_id_exists(self):
        original_arxiv = self.module.maybe_extract_arxiv_figure_urls
        original_pdf = self.module.maybe_extract_pdf_figure_urls
        try:
            self.module.maybe_extract_arxiv_figure_urls = lambda paper_id, config_path, intent: ["https://example.com/a.png"]
            self.module.maybe_extract_pdf_figure_urls = lambda source_spec, config_path: ["https://example.com/b.png"]
            source = self.module.SourceSpec(
                input_value="2401.12345",
                source_kind="arxiv_id",
                source_url="https://arxiv.org/abs/2401.12345",
                canonical_url="https://arxiv.org/abs/2401.12345",
                local_path=None,
                paper_id="2401.12345",
                title_hint="Example",
                raw_text="",
                abstract_text="",
                publish_date_hint="",
                authors_hint=[],
                affiliation_hint="",
                code_url_hint="",
            )
            urls = self.module.maybe_extract_figure_urls(source, None, "architecture")
        finally:
            self.module.maybe_extract_arxiv_figure_urls = original_arxiv
            self.module.maybe_extract_pdf_figure_urls = original_pdf
        self.assertEqual(urls, ["https://example.com/a.png"])

    def test_maybe_extract_figure_urls_falls_back_to_pdf(self):
        original_arxiv = self.module.maybe_extract_arxiv_figure_urls
        original_pdf = self.module.maybe_extract_pdf_figure_urls
        try:
            self.module.maybe_extract_arxiv_figure_urls = lambda paper_id, config_path, intent: []
            self.module.maybe_extract_pdf_figure_urls = lambda source_spec, config_path: ["https://example.com/pdf-fig.png"]
            source = self.module.SourceSpec(
                input_value="/tmp/test.pdf",
                source_kind="local_pdf",
                source_url="/tmp/test.pdf",
                canonical_url="/tmp/test.pdf",
                local_path=Path("/tmp/test.pdf"),
                paper_id="",
                title_hint="Example PDF",
                raw_text="",
                abstract_text="",
                publish_date_hint="",
                authors_hint=[],
                affiliation_hint="",
                code_url_hint="",
            )
            urls = self.module.maybe_extract_figure_urls(source, None, "architecture")
        finally:
            self.module.maybe_extract_arxiv_figure_urls = original_arxiv
            self.module.maybe_extract_pdf_figure_urls = original_pdf
        self.assertEqual(urls, ["https://example.com/pdf-fig.png"])

    def test_maybe_extract_pdf_figure_urls_prefers_caption_aligned_figures(self):
        original_resolve = self.module.resolve_pdf_source_for_figures
        original_caption = self.module.extract_caption_aligned_pdf_figures
        original_embedded = self.module.extract_images_from_pdf_local
        original_upload = self.module.upload_local_figures
        try:
            self.module.resolve_pdf_source_for_figures = lambda source_spec: Path("/tmp/test.pdf")
            self.module.extract_caption_aligned_pdf_figures = lambda pdf_path: [Path("/tmp/caption.png")]
            self.module.extract_images_from_pdf_local = lambda pdf_path: [Path("/tmp/embedded.png")]
            self.module.upload_local_figures = lambda paths, config_path, title_hint: [f"url:{paths[0]}"]
            source = self.module.SourceSpec(
                input_value="/tmp/test.pdf",
                source_kind="local_pdf",
                source_url="/tmp/test.pdf",
                canonical_url="/tmp/test.pdf",
                local_path=Path("/tmp/test.pdf"),
                paper_id="",
                title_hint="Example PDF",
                raw_text="",
                abstract_text="",
                publish_date_hint="",
                authors_hint=[],
                affiliation_hint="",
                code_url_hint="",
            )
            urls = self.module.maybe_extract_pdf_figure_urls(source, None)
        finally:
            self.module.resolve_pdf_source_for_figures = original_resolve
            self.module.extract_caption_aligned_pdf_figures = original_caption
            self.module.extract_images_from_pdf_local = original_embedded
            self.module.upload_local_figures = original_upload
        self.assertEqual(urls, ["url:/tmp/caption.png"])

    def test_maybe_extract_pdf_figure_urls_falls_back_to_embedded_images(self):
        original_resolve = self.module.resolve_pdf_source_for_figures
        original_caption = self.module.extract_caption_aligned_pdf_figures
        original_embedded = self.module.extract_images_from_pdf_local
        original_upload = self.module.upload_local_figures
        try:
            self.module.resolve_pdf_source_for_figures = lambda source_spec: Path("/tmp/test.pdf")
            self.module.extract_caption_aligned_pdf_figures = lambda pdf_path: []
            self.module.extract_images_from_pdf_local = lambda pdf_path: [Path("/tmp/embedded.png")]
            self.module.upload_local_figures = lambda paths, config_path, title_hint: [f"url:{paths[0]}"]
            source = self.module.SourceSpec(
                input_value="/tmp/test.pdf",
                source_kind="local_pdf",
                source_url="/tmp/test.pdf",
                canonical_url="/tmp/test.pdf",
                local_path=Path("/tmp/test.pdf"),
                paper_id="",
                title_hint="Example PDF",
                raw_text="",
                abstract_text="",
                publish_date_hint="",
                authors_hint=[],
                affiliation_hint="",
                code_url_hint="",
            )
            urls = self.module.maybe_extract_pdf_figure_urls(source, None)
        finally:
            self.module.resolve_pdf_source_for_figures = original_resolve
            self.module.extract_caption_aligned_pdf_figures = original_caption
            self.module.extract_images_from_pdf_local = original_embedded
            self.module.upload_local_figures = original_upload
        self.assertEqual(urls, ["url:/tmp/embedded.png"])

    def test_resolve_input_source_for_arxiv_html_url(self):
        original_fetch = self.module.maybe_fetch_url
        try:
            self.module.maybe_fetch_url = lambda url: "<html><head><title>HTML Title | arXiv</title></head></html>" if "/html/" in url else (
                '<html><head><title>Fallback Title | arXiv</title><meta name="citation_date" content="2026-05-12" /></head>'
                '<body><blockquote class="abstract">Abstract: First sentence. Second sentence.</blockquote></body></html>'
            )
            source = self.module.resolve_input_source("https://arxiv.org/html/2501.12345v1")
        finally:
            self.module.maybe_fetch_url = original_fetch
        self.assertEqual(source.source_kind, "arxiv_html_url")
        self.assertEqual(source.paper_id, "2501.12345")
        self.assertEqual(source.canonical_url, "https://arxiv.org/abs/2501.12345")
        self.assertEqual(source.title_hint, "HTML Title")
        self.assertEqual(source.abstract_text, "First sentence. Second sentence.")

    def test_resolve_input_source_for_arxiv_abs_url_prefers_html(self):
        calls = []
        original_fetch = self.module.maybe_fetch_url
        try:
            def fake_fetch(url):
                calls.append(url)
                if "/html/" in url:
                    return '<html><head><title>HTML First | arXiv</title></head><body><blockquote class="abstract">Abstract: HTML abstract.</blockquote></body></html>'
                return '<html><head><title>ABS Fallback | arXiv</title></head></html>'
            self.module.maybe_fetch_url = fake_fetch
            source = self.module.resolve_input_source("https://arxiv.org/abs/2501.12345")
        finally:
            self.module.maybe_fetch_url = original_fetch
        self.assertEqual(source.source_kind, "arxiv_abs_url")
        self.assertEqual(source.title_hint, "HTML First")
        self.assertEqual(source.abstract_text, "HTML abstract.")
        self.assertTrue(calls[0].endswith("/html/2501.12345"))

    def test_build_markdown_contains_expected_sections(self):
        markdown = self.module.build_markdown(
            title="Example Paper",
            language="zh",
            authors=["Alice", "Bob"],
            affiliation="Example Lab",
            source_kind="arxiv_id",
            source_input="1234.5678",
            source_url="https://arxiv.org/abs/1234.5678",
            html_url="https://arxiv.org/html/1234.5678v1",
            pdf_url="https://arxiv.org/pdf/1234.5678.pdf",
            code_url="https://github.com/example/repo",
            translation_url="https://example.com/zh",
            publish_date="2026-05-10",
            domain="agent",
            tags=["paper", "agent"],
            keywords=["planner", "tool-use"],
            image_urls=["https://example.com/fig1.png"],
            hero_image_url="https://example.com/fig1.png",
            method_figure_urls=["https://example.com/fig1.png"],
            result_figure_urls=[],
            insight_figure_urls=[],
            related_topics=["tool-use-workflows"],
            tldr="一句话看懂这篇论文。",
            intuitive_understanding="可以把它理解成带状态管理的工具循环。",
            abstract_en="This paper studies tool use in long-horizon agents.",
            abstract_zh="这篇论文研究长程智能体中的工具使用问题。",
            summary="This paper studies tool use.",
            background_context="Long-horizon agents often break because state and tool effects drift over time.",
            research_problem="Current agents fail on long tasks.",
            core_method="The paper proposes a planner plus tool loop.",
            method_breakdown=["先规划，再执行，再根据反馈修正状态。"],
            key_takeaways=["Tool loops need explicit state."],
            experimental_signals=["Outperforms baseline on long tasks."],
            result_table_markdown="| 指标 | 结果 |\n| --- | --- |\n| Success Rate | 72% |",
            strengths=["Clear system decomposition."],
            limitations=["Only tested in one benchmark."],
            insights=["真正关键的不是更多工具，而是显式状态。"],
            borrowable_ideas=["把显式状态管理抽成独立层。"],
            method_relations=["它比纯 ReAct 式调用更强调状态闭环。"],
            application_scenarios=["长流程工具调用任务。"],
            critical_notes=["Worth linking to knowledge-base-as-agent-memory."],
        )
        self.assertIn("# Example Paper", markdown)
        self.assertIn("## 背景与问题", markdown)
        self.assertIn("https://example.com/fig1.png", markdown)
        self.assertIn("tool-use-workflows", markdown)
        self.assertIn("## 太长不看", markdown)
        self.assertIn("## 直观理解", markdown)
        self.assertIn("## 论文摘要（英文原文）", markdown)
        self.assertIn("## 论文摘要（中文翻译）", markdown)
        self.assertIn("## 方法", markdown)
        self.assertIn("## 结果", markdown)
        self.assertIn("## 洞察", markdown)
        self.assertIn("## 风险与判断", markdown)
        self.assertIn("## 结果速览表", markdown)
        self.assertIn("一句话看懂这篇论文。", markdown)
        self.assertIn("| 指标 | 结果 |", markdown)
        self.assertIn('title: "Example Paper"', markdown)
        self.assertIn("authors:\n  - Alice\n  - Bob", markdown)
        self.assertIn('affiliation: "Example Lab"', markdown)
        self.assertIn('code_url: "https://github.com/example/repo"', markdown)
        self.assertIn("keywords:\n  - planner\n  - tool-use", markdown)
        self.assertIn("tags:\n  - paper\n  - agent", markdown)
        self.assertIn("images:\n  - https://example.com/fig1.png", markdown)
        self.assertIn("related_topics:\n  - tool-use-workflows", markdown)
        self.assertNotIn("\n        title:", markdown)

    def test_derive_fields_from_text_prefers_abstract(self):
        fields = self.module.derive_fields_from_text(
            "Raw body first. Raw body second.",
            "Abstract one. Abstract two. Abstract three.",
        )
        self.assertEqual(fields["research_problem"], "Abstract one.")
        self.assertEqual(fields["core_method"], "Abstract two.")
        self.assertIn("Abstract three.", fields["summary"])

    def test_derive_hjfy_url(self):
        self.assertEqual(self.module.derive_hjfy_url("2406.09246"), "https://hjfy.top/arxiv/2406.09246")
        self.assertEqual(self.module.derive_hjfy_url(""), "")

    def test_quality_gate_payload_rejects_thin_note(self):
        ok, failures = self.module.quality_gate_payload(
            image_urls=[],
            method_breakdown=[],
            experimental_signals=["works well"],
            insights=["important"],
            result_table_markdown="",
            background_context="short",
            research_problem="short",
            core_method="short",
            critical_notes=[],
        )
        self.assertFalse(ok)
        self.assertTrue(failures)

    def test_quality_gate_payload_accepts_strong_note(self):
        ok, failures = self.module.quality_gate_payload(
            image_urls=["https://example.com/fig1.png"],
            method_breakdown=["step one", "step two"],
            experimental_signals=["improves success rate by 20.4% vs baseline"],
            insights=["clear division of labor", "stronger than end-to-end RL fine-tuning"],
            result_table_markdown="| 指标 | 结果 |\n| --- | --- |\n| Success Rate | 72% |",
            background_context="Long-horizon robot control remains difficult because policies need both memory and precise adaptation.",
            research_problem="Prior methods either lose VLA priors or require heavy fine-tuning, making real-world adaptation too expensive.",
            core_method="The paper exposes a compact token interface from a pretrained VLA and performs lightweight online RL on top of it.",
            critical_notes=["worth following for VLA + RL refinement"],
        )
        self.assertTrue(ok)
        self.assertEqual(failures, [])

    def test_extract_code_url_from_html(self):
        html = '<html><body><a href="https://github.com/openvla/openvla">code</a></body></html>'
        self.assertEqual(self.module.extract_code_url_from_html(html), "https://github.com/openvla/openvla")

    def test_extract_code_url_prefers_project_page(self):
        html = '<html><body><a href="https://openvla.github.io">site</a><a href="https://github.com/NVIDIA/TensorRT-LLM">other</a></body></html>'
        self.assertEqual(self.module.extract_code_url_from_html(html), "https://openvla.github.io")

    def test_extract_affiliation_from_html_numbered_lines(self):
        html = "<html><body>1 Stanford University<br>2 UC Berkeley<br>3 Toyota Research Institute</body></html>"
        self.assertEqual(
            self.module.extract_affiliation_from_html(html),
            "Stanford University; UC Berkeley; Toyota Research Institute",
        )

    def test_extract_authors_from_latex_html_block(self):
        html = """
        <div class="ltx_authors">
          Moo Jin Kim<sup>*</sup> Karl Pertsch<sup>*</sup> Siddharth Karamcheti<sup>*</sup>
          Ted Xiao<sup>4</sup> Ashwin Balakrishna<sup>3</sup> Suraj Nair<sup>3</sup>
          Rafael Rafailov<sup>1</sup> Ethan Foster<sup>1</sup> Grace Lam Pannag Sanketi<sup>4</sup>
          Quan Vuong<sup>5</sup> Thomas Kollar<sup>3</sup> Benjamin Burchfiel<sup>3</sup>
          Russ Tedrake<sup>3</sup> Dorsa Sadigh<sup>1</sup> Sergey Levine<sup>2</sup>
          Percy Liang<sup>1</sup> Chelsea Finn<sup>1</sup>
          <a href="https://openvla.github.io">https://openvla.github.io</a>
        </div>
        """
        authors = self.module.extract_authors_from_html(html)
        self.assertIn("Moo Jin Kim", authors)
        self.assertIn("Karl Pertsch", authors)
        self.assertIn("Chelsea Finn", authors)

    def test_extract_affiliation_from_latex_footnote(self):
        html = """
        footnotetext:
        <sup class="ltx_sup">1</sup>Stanford University,
        <sup class="ltx_sup">2</sup>UC Berkeley,
        <sup class="ltx_sup">3</sup>Toyota Research Institute
        """
        self.assertEqual(
            self.module.extract_affiliation_from_html(html),
            "Stanford University; UC Berkeley; Toyota Research Institute",
        )

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
                    "--background-context",
                    "Robotic foundation models need a practical adaptation path that preserves pretrained priors while improving high-precision execution.",
                    "--research-problem",
                    "Directly fine-tuning a large VLA with online RL is expensive, while lightweight RL methods often lose the benefits of pretrained generalist representations.",
                    "--core-method",
                    "The paper exposes a compact token interface from a pretrained VLA and trains a lightweight actor-critic policy on top of it.",
                    "--method-breakdown",
                    "Expose a compact RL token from the pretrained VLA representation.",
                    "--method-breakdown",
                    "Train a lightweight actor-critic head while anchoring actions to the VLA policy.",
                    "--experimental-signal",
                    "Improves success rate by 20% vs baseline in a high-precision setting.",
                    "--insight",
                    "A compact adaptation interface can preserve VLA priors while enabling fast online RL.",
                    "--insight",
                    "Critical-phase-only RL is a pragmatic strategy for real-world robots.",
                    "--critical-note",
                    "Worth following for VLA plus online RL refinement.",
                    "--result-table-markdown",
                    "| 指标 | 结果 |\n| --- | --- |\n| Success Rate | 72% |",
                    "--image-url",
                    "https://example.com/fig1.png",
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
                    "--background-context",
                    "Long-horizon policies need more than a single observation because state, intent, and task progress drift over time.",
                    "--research-problem",
                    "Naive policies fail because they cannot preserve structured state over long sequences of tool or action execution.",
                    "--core-method",
                    "The paper proposes a stronger representation and structured policy loop for the target task.",
                    "--method-breakdown",
                    "Use a compact structured representation.",
                    "--method-breakdown",
                    "Use an iterative policy update around that representation.",
                    "--experimental-signal",
                    "Improves success rate by 18% over a baseline.",
                    "--insight",
                    "Structured intermediate state matters more than raw history length.",
                    "--insight",
                    "The system is easier to adapt than an end-to-end black box policy.",
                    "--critical-note",
                    "Worth linking into the knowledge base.",
                    "--result-table-markdown",
                    "| 指标 | 结果 |\n| --- | --- |\n| Success Rate | 68% |",
                    "--image-url",
                    "https://example.com/fig1.png",
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
                    "--background-context",
                    "Embodied systems need stronger representations for long-horizon decision making under partial observability.",
                    "--research-problem",
                    "Current draft systems do not maintain enough structured context to act reliably over long horizons.",
                    "--core-method",
                    "The paper uses a staged policy structure over a compact latent state.",
                    "--method-breakdown",
                    "Encode context into a compact latent state.",
                    "--method-breakdown",
                    "Use that latent state to guide policy updates.",
                    "--experimental-signal",
                    "Improves throughput by 1.8x compared with baseline.",
                    "--insight",
                    "Latent structure improves controllability.",
                    "--insight",
                    "A staged policy can reduce online adaptation cost.",
                    "--critical-note",
                    "Promising but needs stronger evaluation.",
                    "--result-table-markdown",
                    "| 指标 | 结果 |\n| --- | --- |\n| Throughput | 1.8x |",
                    "--image-url",
                    "https://example.com/fig1.png",
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
