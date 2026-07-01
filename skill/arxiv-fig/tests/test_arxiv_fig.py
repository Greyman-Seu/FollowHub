import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-fig"
SCRIPT_PATH = SKILL_DIR / "arxiv_fig.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"
KEYWORD_PATH = SKILL_DIR / "intent_keywords.yaml"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_fig", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArxivFigSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_skill_files_exist(self):
        self.assertTrue(SKILL_PATH.exists())
        self.assertTrue(SCRIPT_PATH.exists())
        self.assertTrue(KEYWORD_PATH.exists())

    def test_parse_arxiv_id_accepts_id_and_url(self):
        self.assertEqual(self.module.parse_arxiv_id("2604.20834"), "2604.20834")
        self.assertEqual(
            self.module.parse_arxiv_id("https://arxiv.org/abs/2604.20834v1"),
            "2604.20834",
        )

    def test_extract_figures_from_html_resolves_relative_urls_against_final_html_url(self):
        html = (
            '<figure><img src="assets/src/pipeline_new.png">'
            '<figcaption>Figure 1: Pipeline.</figcaption></figure>'
        )

        figures = self.module.extract_figures_from_html(
            html,
            "https://ar5iv.labs.arxiv.org/html/2602.10105v1",
        )

        self.assertEqual(
            figures[0]["image_url"],
            "https://ar5iv.labs.arxiv.org/html/2602.10105v1/assets/src/pipeline_new.png",
        )

    def test_extract_figures_from_html_resolves_arxiv_version_paths_against_html_root(self):
        html = (
            '<figure><img src="2605.13548v3/figures/main_plot2.png">'
            '<figcaption>Figure 1: Overview.</figcaption></figure>'
        )

        figures = self.module.extract_figures_from_html(
            html,
            "https://arxiv.org/html/2605.13548",
        )

        self.assertEqual(
            figures[0]["image_url"],
            "https://arxiv.org/html/2605.13548v3/figures/main_plot2.png",
        )

    def test_parse_tex_captions_handles_nested_braces(self):
        tex = r"""
        \begin{figure}
        \includegraphics[width=\linewidth]{figures/arch_overview.png}
        \caption{Overview with nested \textbf{details} and {extra context}.}
        \end{figure}
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = Path(tmpdir) / "paper.tex"
            tex_path.write_text(tex, encoding="utf-8")
            captions = self.module.parse_tex_captions(tmpdir)

        self.assertIn("arch_overview.png", captions)
        self.assertIn("Overview with nested", captions["arch_overview.png"])
        self.assertIn("extra context", captions["arch_overview.png"])

    def test_extract_captions_from_pdf_text_handles_multiline_captions(self):
        sample_text = """
        Intro text mentioning Figure 1 in passing.

        Figure 1
        Overview. JoyAI-RA is trained on four complementary data sources:
        web data, egocentric videos, simulation data.

        Figure 2: Distribution analysis of pretraining data.
        """
        completed = subprocess.CompletedProcess(
            args=["pdftotext", "paper.pdf", "-"],
            returncode=0,
            stdout=sample_text,
            stderr="",
        )
        with mock.patch.object(self.module.subprocess, "run", return_value=completed):
            captions = self.module.extract_captions_from_pdf_text("paper.pdf")

        self.assertIn(1, captions)
        self.assertIn("Overview. JoyAI-RA is trained", captions[1])
        self.assertIn(2, captions)
        self.assertIn("Distribution analysis", captions[2])

    def test_build_paper_dir_name_uses_arxiv_id_and_slugified_title(self):
        paper_dir = self.module.build_paper_dir_name(
            "2604.20834",
            "JoyAI-RA: Coordinated Embodied Learning for Mobile Manipulation",
        )
        self.assertTrue(paper_dir.startswith("2604.20834-"))
        self.assertIn("joyai-ra", paper_dir)
        self.assertNotIn(":", paper_dir)

    def test_select_relevant_figures_prefers_architecture_caption(self):
        figures = [
            {
                "figure_number": 1,
                "caption": "Figure 1: Overview of the proposed architecture for multimodal planning.",
                "image_url": None,
                "image_path": "/tmp/fig1.png",
                "source": "arxiv_source",
            },
            {
                "figure_number": 2,
                "caption": "Figure 2: Ablation study over training schedules.",
                "image_url": None,
                "image_path": "/tmp/fig2.png",
                "source": "arxiv_source",
            },
        ]
        rules = self.module.load_intent_keywords(KEYWORD_PATH)
        selected = self.module.select_relevant_figures(
            figures,
            "找这篇论文的架构图",
            rules,
            max_results=2,
        )

        self.assertEqual([figure["figure_number"] for figure in selected], [1])
        self.assertGreater(selected[0]["match_score"], 0)
        self.assertEqual(selected[0]["matched_intent"], "architecture")

    def test_select_relevant_figures_supports_multiple_intents_without_default_cap(self):
        figures = [
            {
                "figure_number": 1,
                "caption": "Figure 1: Overview of the proposed architecture for multimodal planning.",
                "image_url": None,
                "image_path": "/tmp/fig1.png",
                "source": "arxiv_source",
            },
            {
                "figure_number": 2,
                "caption": "Figure 2: System workflow and deployment pipeline.",
                "image_url": None,
                "image_path": "/tmp/fig2.png",
                "source": "arxiv_source",
            },
            {
                "figure_number": 3,
                "caption": "Figure 3: Ablation study over training schedules.",
                "image_url": None,
                "image_path": "/tmp/fig3.png",
                "source": "arxiv_source",
            },
        ]
        rules = self.module.load_intent_keywords(KEYWORD_PATH)
        selected = self.module.select_relevant_figures(
            figures,
            "architecture, system",
            rules,
        )

        self.assertEqual([figure["figure_number"] for figure in selected], [1, 2])
        self.assertIn("architecture", selected[0]["matched_intents"])
        self.assertIn("system", selected[1]["matched_intents"])

    def test_infer_default_max_results_prefers_one_for_single_intent(self):
        self.assertEqual(self.module.infer_default_max_results("main figure", None), 1)
        self.assertEqual(self.module.infer_default_max_results("architecture", None), 1)
        self.assertIsNone(self.module.infer_default_max_results("architecture, system", None))
        self.assertEqual(self.module.infer_default_max_results("architecture", 3), 3)

    def test_finalize_selected_figures_uploads_only_selected_local_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "candidate.png"
            Image.new("RGB", (2400, 1200), color="white").save(local_path)
            figures = [
                {
                    "figure_number": 1,
                    "caption": "Architecture overview.",
                    "image_url": None,
                    "image_path": str(local_path),
                    "source": "arxiv_source",
                },
                {
                    "figure_number": 2,
                    "caption": "HTML figure.",
                    "image_url": "https://arxiv.org/html/2604.20834v1/x2.png",
                    "image_path": None,
                    "source": "html",
                },
            ]
            config = {
                "arxiv_fig": {
                    "cloudflare_bucket_dir": "papers",
                    "max_image_long_side": 1600,
                    "jpeg_quality": 82,
                }
            }
            uploads = []

            def fake_upload(src_path, storage_key, config_path):
                uploads.append((Path(src_path), storage_key, str(config_path)))
                return {
                    "url": f"https://followhub.tenstep.top/{storage_key}",
                    "storage_key": storage_key,
                }

            finalized = self.module.finalize_selected_figures(
                figures,
                arxiv_id="2604.20834",
                paper_title="JoyAI RA",
                config=config,
                config_path=Path("/tmp/config.yaml"),
                upload_func=fake_upload,
            )

        self.assertEqual(len(uploads), 1)
        self.assertIn("2604.20834-joyai-ra", uploads[0][1])
        self.assertEqual(finalized[1]["image_url"], "https://arxiv.org/html/2604.20834v1/x2.png")
        self.assertTrue(finalized[0]["image_url"].startswith("https://followhub.tenstep.top/"))
        self.assertEqual(finalized[0]["paper_dir"], "2604.20834-joyai-ra")
        self.assertIn("storage_key", finalized[0])

    def test_finalize_selected_figures_keeps_local_path_without_cloudflare_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "candidate.png"
            Image.new("RGB", (800, 400), color="white").save(local_path)
            figures = [
                {
                    "figure_number": 1,
                    "caption": "Pipeline overview.",
                    "image_url": None,
                    "image_path": str(local_path),
                    "source": "pdf",
                }
            ]
            finalized = self.module.finalize_selected_figures(
                figures,
                arxiv_id="2604.20834",
                paper_title="JoyAI RA",
                config={"arxiv_fig": {}},
                config_path=Path("/tmp/config.yaml"),
                upload_func=mock.Mock(side_effect=AssertionError("should not upload")),
            )

        self.assertIsNone(finalized[0]["image_url"])
        self.assertEqual(finalized[0]["image_path"], str(local_path))
        self.assertNotIn("storage_key", finalized[0])

    def test_finalize_selected_figures_falls_back_to_local_on_upload_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "candidate.png"
            Image.new("RGB", (800, 400), color="white").save(local_path)
            figures = [
                {
                    "figure_number": 1,
                    "caption": "Pipeline overview.",
                    "image_url": None,
                    "image_path": str(local_path),
                    "source": "pdf",
                }
            ]

            finalized = self.module.finalize_selected_figures(
                figures,
                arxiv_id="2604.20834",
                paper_title="JoyAI RA",
                config={"arxiv_fig": {"cloudflare_bucket_dir": "papers"}},
                config_path=Path("/tmp/config.yaml"),
                upload_func=mock.Mock(side_effect=RuntimeError("rclone missing")),
            )

        self.assertIsNone(finalized[0]["image_url"])
        self.assertEqual(finalized[0]["image_path"], str(local_path))
        self.assertIn("upload_error", finalized[0])

    def test_compress_image_for_upload_limits_long_side(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "large.png"
            Image.new("RGB", (3200, 1800), color="white").save(source_path)

            compressed_path = self.module.compress_image_for_upload(
                source_path,
                Path(tmpdir),
                max_long_side=1600,
                jpeg_quality=82,
            )

            with Image.open(compressed_path) as image:
                self.assertLessEqual(max(image.size), 1600)
            self.assertEqual(compressed_path.suffix.lower(), ".jpg")

    def test_record_keyword_suggestion_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "keyword_suggestions.jsonl"
            figure = {
                "figure_number": 1,
                "caption": "Overview of the proposed architecture for multimodal planning.",
                "image_path": "/tmp/fig1.png",
                "source": "arxiv_source",
            }

            self.module.record_keyword_suggestion(
                "architecture",
                figure,
                match_score=7,
                suggestion_log_path=log_path,
            )

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])

        self.assertEqual(payload["intent"], "architecture")
        self.assertEqual(payload["figure_number"], 1)
        self.assertIn("architecture", payload["suggested_keywords"])

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("/arxiv-fig", result.stdout)


if __name__ == "__main__":
    unittest.main()
