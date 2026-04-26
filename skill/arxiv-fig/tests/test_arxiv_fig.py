import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-fig"
SCRIPT_PATH = SKILL_DIR / "arxiv_fig.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"


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

    def test_parse_arxiv_id_accepts_id_and_url(self):
        self.assertEqual(self.module.parse_arxiv_id("2604.20834"), "2604.20834")
        self.assertEqual(
            self.module.parse_arxiv_id("https://arxiv.org/abs/2604.20834v1"),
            "2604.20834",
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
