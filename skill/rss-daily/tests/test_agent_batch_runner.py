import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "skill" / "rss-daily" / "agent_batch_runner.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rss_agent_batch_runner", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runner = load_module()


class AgentBatchRunnerTests(unittest.TestCase):
    def test_plan_prefilter_batches_writes_manifest_and_batch_inputs(self):
        payload = {
            "mode": "rss-prefilter",
            "entries": [
                {"id": "x:1", "title": "A"},
                {"id": "x:2", "title": "B"},
                {"id": "x:3", "title": "C"},
                {"id": "x:4", "title": "D"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "prefilter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            manifest = runner.plan_worker_batches(
                input_path=input_path,
                output_dir=root / "batches",
                entries_key="entries",
                mode="rss-prefilter-batches",
                recommended_worker="rss-prefilter",
                fallback_batch_size=3,
            )
            self.assertEqual(manifest["batch_count"], 2)
            self.assertEqual(manifest["item_count"], 4)
            first_batch = json.loads((root / "batches" / "batch-001.input.json").read_text(encoding="utf-8"))
            self.assertEqual(first_batch["batch"]["batch_count"], 2)
            self.assertEqual(len(first_batch["entries"]), 3)

    def test_merge_prefilter_results_validates_and_merges(self):
        payload = {
            "mode": "rss-prefilter",
            "entries": [
                {"id": "x:1", "title": "A"},
                {"id": "x:2", "title": "B"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "prefilter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            runner.plan_worker_batches(
                input_path=input_path,
                output_dir=root / "batches",
                entries_key="entries",
                mode="rss-prefilter-batches",
                recommended_worker="rss-prefilter",
                fallback_batch_size=1,
            )
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps({"items": [{"id": "x:1", "decision": "keep", "reason": "ok"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "batches" / "batch-002.result.json").write_text(
                json.dumps({"items": [{"id": "x:2", "decision": "drop", "reason": "noise"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            merged = runner.merge_prefilter_results(
                input_path=input_path,
                batch_dir=root / "batches",
                output_path=root / "prefilter_results.json",
            )
            self.assertEqual(len(merged["items"]), 2)
            self.assertEqual({row["decision"] for row in merged["items"]}, {"keep", "drop"})

    def test_merge_filter_results_preserves_summary_fields(self):
        payload = {
            "mode": "rss-filter",
            "entries": [
                {"id": "x:1", "title": "A", "source_type": "x", "summary": "sum a", "content_text": "content a", "url": "https://x.com/a"},
                {"id": "x:2", "title": "B", "source_type": "x", "summary": "sum b", "content_text": "content b", "url": "https://x.com/b"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "filter_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            runner.plan_worker_batches(
                input_path=input_path,
                output_dir=root / "batches",
                entries_key="entries",
                mode="rss-filter-batches",
                recommended_worker="rss-filter",
                fallback_batch_size=2,
            )
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "x:1",
                                "include_in_digest": True,
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "one_liner_zh": "一句话",
                                "summary_cn": "",
                                "reason": "fit",
                            },
                            {
                                "id": "x:2",
                                "include_in_digest": False,
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
            self.assertTrue(merged["items"][0]["include_in_digest"])
            self.assertEqual(merged["items"][0]["one_liner_zh"], "一句话")
            self.assertEqual(merged["items"][0]["source_type"], "x")
            self.assertEqual(merged["items"][0]["title"], "A")
            self.assertEqual(merged["items"][0]["content_text"], "content a")
            self.assertEqual(merged["items"][0]["summary_generated_by"], "agent")

    def test_plan_and_merge_enrich_results(self):
        payload = {
            "entries": [
                {
                    "id": "x:1",
                    "source_type": "x",
                    "one_liner_zh": "",
                    "summary_cn": "",
                    "summary_generated_by": "",
                },
                {
                    "id": "wechat:1",
                    "source_type": "wechat",
                    "one_liner_zh": "",
                    "summary_cn": "",
                    "summary_generated_by": "",
                },
            ],
            "agent_completion": {
                "required": True,
                "task_count": 2,
                "recommended_batch_size": 1,
                "recommended_worker": "rss-enrich-agent-completion",
                "tasks": [
                    {"id": "x:1", "agent_summary_prompt": "x prompt"},
                    {"id": "wechat:1", "agent_summary_prompt": "wechat prompt"},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "enrich_results.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            manifest = runner.plan_enrich_batches(input_path=input_path, output_dir=root / "batches")
            self.assertEqual(manifest["batch_count"], 2)
            (root / "batches" / "batch-001.result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "x:1",
                                "one_liner_zh": "X 摘要",
                                "summary_cn": "",
                                "summary_generated_by": "agent",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "batches" / "batch-002.result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "wechat:1",
                                "one_liner_zh": "微信一句话",
                                "summary_cn": "微信两句话摘要",
                                "summary_generated_by": "agent",
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
            by_id = {entry["id"]: entry for entry in merged["entries"]}
            self.assertEqual(by_id["x:1"]["one_liner_zh"], "X 摘要")
            self.assertEqual(by_id["x:1"]["summary_cn"], "")
            self.assertEqual(by_id["wechat:1"]["summary_cn"], "微信两句话摘要")

    def test_status_reports_completed_batches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = {
                "mode": "rss-enrich-agent-completion",
                "batches": [
                    {"batch_id": "001", "result_path": "batch-001.result.json"},
                    {"batch_id": "002", "result_path": "batch-002.result.json"},
                ],
            }
            (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            (root / "batch-001.result.json").write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
            payload = runner.status(root)
            self.assertEqual(payload["completed_batch_count"], 1)
            self.assertEqual(payload["pending_batch_ids"], ["002"])


if __name__ == "__main__":
    unittest.main()
