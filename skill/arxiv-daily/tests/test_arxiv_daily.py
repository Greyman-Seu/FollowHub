import importlib.util
import json
import subprocess
import sys
import tempfile
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

    def test_build_enrich_input_preserves_existing_chinese_fields_from_filter(self):
        raw_payload = {
            "date": "2026-05-26",
            "entries": [
                {
                    "id": "2605.25044",
                    "title": "X-DiffVLA",
                    "summary": "English abstract.",
                }
            ],
        }
        filter_payload = {
            "items": [
                {
                    "arxiv_id": "2605.25044",
                    "include_in_follow": True,
                    "one_liner_zh": "中文一句话。",
                    "summary_cn": "中文摘要。",
                    "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                    "reason": "纳入原因。",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "enrich_input.json"
            payload = self.module.build_enrich_input(raw_payload, filter_payload, output_path)
            self.assertEqual(payload["selected_ids"], ["2605.25044"])
            self.assertEqual(len(payload["entries"]), 1)
            row = payload["entries"][0]
            self.assertEqual(row["one_liner_zh"], "中文一句话。")
            self.assertEqual(row["summary_cn"], "中文摘要。")
            self.assertEqual(row["filter_reason"], "纳入原因。")
            self.assertEqual(row["domains"][0]["slug"], "physical-embodied-intelligence")
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["entries"][0]["summary_cn"], "中文摘要。")

    def test_organization_only_agent_completion_does_not_block_publish(self):
        enrich_payload = {
            "agent_completion": {
                "tasks": [
                    {
                        "arxiv_id": "2605.25044",
                        "needs_agent_summary": False,
                        "needs_summary_cn_translation": False,
                        "needs_one_liner_zh": False,
                        "needs_related_organizations": True,
                    }
                ]
            }
        }
        self.module.ensure_enrich_agent_completion_done(enrich_payload, Path("/tmp/enrich_results.json"))

    def test_summary_agent_completion_still_blocks_publish(self):
        enrich_payload = {
            "agent_completion": {
                "tasks": [
                    {
                        "arxiv_id": "2605.25044",
                        "needs_agent_summary": True,
                        "needs_summary_cn_translation": True,
                        "needs_one_liner_zh": False,
                        "needs_related_organizations": False,
                    }
                ]
            }
        }
        with self.assertRaises(SystemExit) as ctx:
            self.module.ensure_enrich_agent_completion_done(enrich_payload, Path("/tmp/enrich_results.json"))
        self.assertIn("Pending tasks: 1", str(ctx.exception))

    def test_run_enrich_enables_external_metadata(self):
        captured = {}
        original_run_command = self.module.run_command
        original_load_json = self.module.load_json
        try:
            def fake_run_command(args, *, cwd):
                captured["args"] = args
                output_index = args.index("--output") + 1
                output_path = Path(args[output_index])
                output_path.write_text(json.dumps({"entries": [], "agent_completion": {"required": False, "task_count": 0, "tasks": []}}), encoding="utf-8")
                class Proc:
                    stdout = "{}"
                return Proc()

            self.module.run_command = fake_run_command
            self.module.load_json = lambda path: {"entries": [], "agent_completion": {"required": False, "task_count": 0, "tasks": []}}
            with tempfile.TemporaryDirectory() as tmpdir:
                self.module.run_enrich(
                    Path("/tmp/followhub.yaml"),
                    Path(tmpdir) / "input.json",
                    Path(tmpdir) / "output.json",
                )
            self.assertIn("--enable-external-metadata", captured["args"])
        finally:
            self.module.run_command = original_run_command
            self.module.load_json = original_load_json


if __name__ == "__main__":
    unittest.main()
