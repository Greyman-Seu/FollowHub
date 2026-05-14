import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-daily"
SCRIPT_PATH = SKILL_DIR / "run_daily.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_daily", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ArxivDailySkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("arxiv-daily", result.stdout)
        self.assertIn("daily", result.stdout)

    def test_skill_doc_describes_agent_native_workflow(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("workflow skill, not a CLI-first skill", content)
        self.assertIn("The primary entrypoint is this `SKILL.md`.", content)
        self.assertIn("Subagents are the recommended execution mode", content)

    def test_missing_worker_results_message_points_to_agent_workflow(self):
        message = self.module.missing_worker_results_message(
            "arxiv-title-prefilter",
            Path("/tmp/prefilter_input.json"),
            Path("/tmp/prefilter_results.json"),
        )
        self.assertIn("agent/subagent workers", message)
        self.assertIn("prefilter_results.json is missing", message)
        self.assertIn("arxiv-title-prefilter", message)

    def test_daily_parser_defaults_to_publish(self):
        parser = self.module.build_parser()
        args = parser.parse_args(["daily"])
        self.assertFalse(args.no_publish)


if __name__ == "__main__":
    unittest.main()
