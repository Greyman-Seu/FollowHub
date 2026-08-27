import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "skill" / "arxiv-daily" / "agent_batch_runner.py"


def load_module():
    spec = importlib.util.spec_from_file_location("arxiv_agent_batch_runner", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runner = load_module()


class ArxivAgentBatchRunnerTests(unittest.TestCase):
    def test_plan_prefilter_batches_writes_manifest_and_batch_inputs(self):
        payload = {
            "mode": "title-prefilter",
            "entries": [
                {"arxiv_id": "1", "title": "A"},
                {"arxiv_id": "2", "title": "B"},
                {"arxiv_id": "3", "title": "C"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "prefilter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            manifest = runner.plan_entry_batches(
                input_path=input_path,
                output_dir=root / "batches",
                mode="title-prefilter",
                batch_mode="arxiv-title-prefilter",
                fallback_batch_size=2,
            )
            self.assertEqual(manifest["batch_count"], 2)
            first_batch = json.loads((root / "batches" / "batch-001.input.json").read_text(encoding="utf-8"))
            self.assertEqual(first_batch["batch"]["batch_count"], 2)
            self.assertEqual(len(first_batch["entries"]), 2)

    def test_merge_prefilter_results_validates_and_merges(self):
        payload = {
            "mode": "title-prefilter",
            "entries": [
                {"arxiv_id": "1", "title": "A"},
                {"arxiv_id": "2", "title": "B"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "prefilter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            runner.plan_entry_batches(
                input_path=input_path,
                output_dir=root / "batches",
                mode="title-prefilter",
                batch_mode="arxiv-title-prefilter",
                fallback_batch_size=1,
            )
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps({"items": [{"arxiv_id": "1", "decision": "keep", "reason": "fit"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "batches" / "batch-002.result.json").write_text(
                json.dumps({"items": [{"arxiv_id": "2", "decision": "drop", "reason": "noise"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            merged = runner.merge_prefilter_results(
                input_path=input_path,
                batch_dir=root / "batches",
                output_path=root / "prefilter_results.json",
            )
            self.assertEqual(len(merged["items"]), 2)
            self.assertEqual({row["decision"] for row in merged["items"]}, {"keep", "drop"})

    def test_merge_filter_results_preserves_worker_fields(self):
        payload = {
            "mode": "filter",
            "entries": [
                {"id": "1", "title": "A"},
                {"id": "2", "title": "B"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "filter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            runner.plan_entry_batches(
                input_path=input_path,
                output_dir=root / "batches",
                mode="filter",
                batch_mode="arxiv-filter-batches",
                fallback_batch_size=2,
            )
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "arxiv_id": "1",
                                "include_in_follow": True,
                                "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                                "one_liner_zh": "一句话",
                                "summary_cn": "中文摘要",
                                "reason": "fit",
                            },
                            {
                                "arxiv_id": "2",
                                "include_in_follow": False,
                                "domains": [],
                                "one_liner_zh": "",
                                "summary_cn": "",
                                "reason": "noise",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            merged = runner.merge_filter_results(
                input_path=input_path,
                batch_dir=root / "batches",
                output_path=root / "filter_results.json",
            )
            self.assertEqual(len(merged["items"]), 2)
            self.assertTrue(merged["items"][0]["include_in_follow"])
            self.assertEqual(merged["items"][0]["one_liner_zh"], "一句话")

    def test_plan_and_merge_enrich_results(self):
        payload = {
            "entries": [
                {
                    "id": "1",
                    "one_liner_zh": "",
                    "summary_cn": "",
                    "related_organizations": [],
                    "related_companies": [],
                    "needs_agent_summary": True,
                    "needs_summary_cn_translation": True,
                    "needs_one_liner_zh": True,
                    "needs_related_organizations": True,
                    "agent_summary_prompt": "summary prompt",
                    "agent_translation_prompt": "translation prompt",
                    "agent_one_liner_prompt": "one-liner prompt",
                    "agent_organization_prompt": "org prompt",
                }
            ],
            "agent_completion": {
                "required": True,
                "task_count": 1,
                "recommended_batch_size": 1,
                "recommended_worker": "arxiv-enrich-agent-completion",
                "tasks": [
                    {
                        "arxiv_id": "1",
                        "needs_agent_summary": True,
                        "needs_summary_cn_translation": True,
                        "needs_one_liner_zh": True,
                        "needs_related_organizations": True,
                        "agent_summary_prompt": "summary prompt",
                        "agent_translation_prompt": "translation prompt",
                        "agent_one_liner_prompt": "one-liner prompt",
                        "agent_organization_prompt": "org prompt",
                    }
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "enrich_results.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            manifest = runner.plan_enrich_batches(input_path=input_path, output_dir=root / "batches")
            self.assertEqual(manifest["batch_count"], 1)
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "arxiv_id": "1",
                                "one_liner_zh": "一句话",
                                "summary_cn": "中文摘要",
                                "related_organizations": ["Org A"],
                                "related_companies": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            merged = runner.merge_enrich_results(
                input_path=input_path,
                batch_dir=root / "batches",
                output_path=root / "enrich_merged.json",
            )
            self.assertFalse(merged["agent_completion"]["required"])
            self.assertEqual(merged["entries"][0]["one_liner_zh"], "一句话")
            self.assertEqual(merged["entries"][0]["related_organizations"], ["Org A"])


if __name__ == "__main__":
    unittest.main()
