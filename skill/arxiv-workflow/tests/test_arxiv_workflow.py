import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "arxiv-workflow"
SCRIPT_PATH = SKILL_DIR / "arxiv_workflow.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"
DAILY_FIXTURE = REPO_ROOT / "skill" / "arxiv-view" / "tests" / "fixtures" / "daily.json"
BACKFILL_FIXTURE = REPO_ROOT / "skill" / "arxiv-view" / "tests" / "fixtures" / "backfill-overview.md"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_workflow", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArxivWorkflowSkillTests(unittest.TestCase):
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
        self.assertIn("arxiv-workflow", result.stdout)
        self.assertIn("compose", result.stdout)

    def test_plan_enrich_batches_single_id_is_inline(self):
        plan = self.module.plan_enrich_batches(["2604.11111"])
        self.assertEqual(plan["mode"], "inline")
        self.assertEqual(plan["groups"], [["2604.11111"]])

    def test_plan_enrich_batches_four_ids_use_one_worker_per_id(self):
        ids = ["a", "b", "c", "d"]
        plan = self.module.plan_enrich_batches(ids)
        self.assertEqual(plan["mode"], "subagent")
        self.assertEqual(plan["groups"], [["a"], ["b"], ["c"], ["d"]])

    def test_plan_enrich_batches_eight_ids_use_balanced_groups(self):
        ids = [f"id{i}" for i in range(8)]
        plan = self.module.plan_enrich_batches(ids)
        self.assertEqual(plan["mode"], "subagent")
        self.assertEqual(plan["groups"], [ids[:4], ids[4:]])

    def test_compose_from_result_builds_view_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self.module.compose_from_result(
                input_path=DAILY_FIXTURE,
                workspace=Path(tmpdir),
            )
            self.assertTrue((Path(tmpdir) / "view" / "index.html").exists())
            self.assertTrue((Path(tmpdir) / "workflow.json").exists())
            self.assertEqual(manifest["result_mode"], "daily")
            self.assertEqual(manifest["selected_ids"], ["2604.21924", "2604.21241"])
            self.assertEqual(manifest["enrich_plan"]["mode"], "subagent")

    def test_compose_from_backfill_groups_days_and_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self.module.compose_from_result(
                input_path=BACKFILL_FIXTURE,
                workspace=Path(tmpdir),
            )
            self.assertEqual(manifest["result_mode"], "backfill")
            self.assertEqual(manifest["item_count"], 3)
            self.assertIn("2026-04-24", manifest["days"])
            self.assertIn("2026-04-25", manifest["days"])

    def test_compose_with_explicit_selected_ids_overrides_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self.module.compose_from_result(
                input_path=DAILY_FIXTURE,
                workspace=Path(tmpdir),
                selected_ids=["2604.21241"],
            )
            self.assertEqual(manifest["selected_ids"], ["2604.21241"])
            self.assertEqual(manifest["enrich_plan"]["mode"], "inline")

    def test_cli_compose_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "compose",
                    "--input",
                    str(DAILY_FIXTURE),
                    "--workspace",
                    str(tmpdir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            manifest = json.loads((Path(tmpdir) / "workflow.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result_mode"], "daily")
            self.assertTrue((Path(tmpdir) / "view" / "data.json").exists())


if __name__ == "__main__":
    unittest.main()
