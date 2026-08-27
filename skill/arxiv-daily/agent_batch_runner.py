#!/usr/bin/env python3
"""Batch planner and merger for standalone arXiv daily workers."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


HELP_TEXT = """\
arxiv-agent-batch-runner: Plan and merge batched arXiv worker tasks.

Usage:
    arxiv-agent-batch-runner help
    arxiv-agent-batch-runner plan-prefilter --input /path/to/prefilter_input.json --output-dir ./prefilter-batches
    arxiv-agent-batch-runner merge-prefilter --input /path/to/prefilter_input.json --batch-dir ./prefilter-batches --output /path/to/prefilter_results.json
    arxiv-agent-batch-runner plan-filter --input /path/to/filter_input.json --output-dir ./filter-batches
    arxiv-agent-batch-runner merge-filter --input /path/to/filter_input.json --batch-dir ./filter-batches --output /path/to/filter_results.json
    arxiv-agent-batch-runner plan-enrich --input /path/to/enrich_results.json --output-dir ./enrich-batches
    arxiv-agent-batch-runner merge-enrich --input /path/to/enrich_results.json --batch-dir ./enrich-batches --output /path/to/enrich_results.json
    arxiv-agent-batch-runner status --batch-dir ./enrich-batches
"""


def fail(message: str) -> None:
    raise SystemExit(message)


def log(message: str, **details: Any) -> None:
    payload: Dict[str, Any] = {"message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False))


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def chunked(items: Sequence[Dict[str, Any]], batch_size: int) -> Iterable[List[Dict[str, Any]]]:
    step = max(1, int(batch_size))
    for start in range(0, len(items), step):
        yield list(items[start : start + step])


def batch_id(index: int) -> str:
    return f"{index:03d}"


def default_batch_size(value: int | None, fallback: int) -> int:
    if value and int(value) > 0:
        return int(value)
    return fallback


def _entry_arxiv_id(entry: Dict[str, Any]) -> str:
    return str(entry.get("arxiv_id") or entry.get("id") or "").strip()


def plan_entry_batches(
    *,
    input_path: Path,
    output_dir: Path,
    mode: str,
    batch_mode: str,
    fallback_batch_size: int,
    batch_size_override: int | None = None,
) -> Dict[str, Any]:
    payload = load_json(input_path)
    entries = list(payload.get("entries") or [])
    if not entries:
        fail(f"{input_path} does not contain any 'entries'.")
    batch_size = default_batch_size(batch_size_override, fallback_batch_size)
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_records = []
    for index, batch_entries in enumerate(chunked(entries, batch_size), start=1):
        identifier = batch_id(index)
        batch_input_path = output_dir / f"batch-{identifier}.input.json"
        batch_result_path = output_dir / f"batch-{identifier}.result.json"
        batch_payload = {key: value for key, value in payload.items() if key != "entries"}
        batch_payload["mode"] = mode
        batch_payload["batch"] = {
            "batch_id": identifier,
            "batch_index": index,
            "batch_count": 0,
            "recommended_worker": mode,
        }
        batch_payload["entries"] = batch_entries
        batch_payload["item_count"] = len(batch_entries)
        batch_payload["count"] = len(batch_entries)
        save_json(batch_input_path, batch_payload)
        batch_records.append(
            {
                "batch_id": identifier,
                "batch_index": index,
                "input_path": batch_input_path.name,
                "result_path": batch_result_path.name,
                "arxiv_ids": [_entry_arxiv_id(entry) for entry in batch_entries],
                "item_count": len(batch_entries),
            }
        )

    total_batches = len(batch_records)
    for record in batch_records:
        batch_input_path = output_dir / str(record["input_path"])
        batch_payload = load_json(batch_input_path)
        batch_payload["batch"]["batch_count"] = total_batches
        save_json(batch_input_path, batch_payload)

    manifest = {
        "mode": batch_mode,
        "input_path": str(input_path),
        "batch_size": batch_size,
        "batch_count": total_batches,
        "item_count": len(entries),
        "batches": batch_records,
    }
    save_json(output_dir / "manifest.json", manifest)
    log(
        "planned-batches",
        mode=batch_mode,
        output_dir=str(output_dir),
        batch_count=total_batches,
        item_count=len(entries),
        batch_size=batch_size,
    )
    return manifest


def load_manifest(batch_dir: Path) -> Dict[str, Any]:
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        fail(f"Missing batch manifest: {manifest_path}")
    return load_json(manifest_path)


def normalize_result_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [dict(item) for item in items]
    fail("Batch result must be a JSON object with an 'items' list or a JSON list.")


def merge_prefilter_results(*, input_path: Path, batch_dir: Path, output_path: Path) -> Dict[str, Any]:
    source = load_json(input_path)
    manifest = load_manifest(batch_dir)
    allowed_ids = {_entry_arxiv_id(item) for item in (source.get("entries") or [])}
    merged_items: List[Dict[str, Any]] = []
    seen = set()
    for batch in manifest.get("batches") or []:
        result_path = batch_dir / str(batch.get("result_path") or "")
        if not result_path.exists():
            fail(f"Missing batch result: {result_path}")
        items = normalize_result_items(load_json(result_path))
        batch_ids = set(batch.get("arxiv_ids") or [])
        for item in items:
            arxiv_id = str(item.get("arxiv_id") or "")
            decision = str(item.get("decision") or "")
            if arxiv_id not in allowed_ids:
                fail(f"prefilter batch result contains unknown arxiv_id: {arxiv_id}")
            if arxiv_id not in batch_ids:
                fail(f"prefilter batch result contains arxiv_id outside its assigned batch: {arxiv_id}")
            if decision not in {"keep", "drop", "uncertain", "direct-pass"}:
                fail(f"Invalid prefilter decision for {arxiv_id}: {decision}")
            if arxiv_id in seen:
                fail(f"Duplicate prefilter result for arxiv_id: {arxiv_id}")
            seen.add(arxiv_id)
            merged_items.append(
                {
                    "arxiv_id": arxiv_id,
                    "decision": decision,
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
    missing = sorted(allowed_ids - seen)
    if missing:
        fail(f"Missing prefilter decisions for {len(missing)} papers.")
    payload = {
        "mode": "arxiv-title-prefilter-results",
        "items": merged_items,
        "generated_by": "arxiv-agent-batch-runner",
    }
    save_json(output_path, payload)
    log("merged-prefilter-results", output_path=str(output_path), item_count=len(merged_items))
    return payload


def merge_filter_results(*, input_path: Path, batch_dir: Path, output_path: Path) -> Dict[str, Any]:
    source = load_json(input_path)
    manifest = load_manifest(batch_dir)
    allowed_ids = {_entry_arxiv_id(item) for item in (source.get("entries") or [])}
    merged_items: List[Dict[str, Any]] = []
    seen = set()
    for batch in manifest.get("batches") or []:
        result_path = batch_dir / str(batch.get("result_path") or "")
        if not result_path.exists():
            fail(f"Missing batch result: {result_path}")
        items = normalize_result_items(load_json(result_path))
        batch_ids = set(batch.get("arxiv_ids") or [])
        for item in items:
            arxiv_id = str(item.get("arxiv_id") or "")
            if arxiv_id not in allowed_ids:
                fail(f"filter batch result contains unknown arxiv_id: {arxiv_id}")
            if arxiv_id not in batch_ids:
                fail(f"filter batch result contains arxiv_id outside its assigned batch: {arxiv_id}")
            if arxiv_id in seen:
                fail(f"Duplicate filter result for arxiv_id: {arxiv_id}")
            seen.add(arxiv_id)
            merged_items.append(
                {
                    "arxiv_id": arxiv_id,
                    "include_in_follow": bool(item.get("include_in_follow", False)),
                    "domains": list(item.get("domains") or []),
                    "one_liner_zh": str(item.get("one_liner_zh") or "").strip(),
                    "summary_cn": str(item.get("summary_cn") or "").strip(),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
    missing = sorted(allowed_ids - seen)
    if missing:
        fail(f"Missing filter decisions for {len(missing)} papers.")
    payload = {
        "mode": "arxiv-filter-results",
        "items": merged_items,
        "generated_by": "arxiv-agent-batch-runner",
    }
    save_json(output_path, payload)
    log("merged-filter-results", output_path=str(output_path), item_count=len(merged_items))
    return payload


def plan_enrich_batches(*, input_path: Path, output_dir: Path, batch_size_override: int | None = None) -> Dict[str, Any]:
    payload = load_json(input_path)
    agent_completion = payload.get("agent_completion") or {}
    tasks = list(agent_completion.get("tasks") or [])
    if not tasks:
        fail(f"{input_path} does not contain pending agent completion tasks.")
    batch_size = default_batch_size(batch_size_override, int(agent_completion.get("recommended_batch_size") or 3))
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_records = []
    for index, batch_tasks in enumerate(chunked(tasks, batch_size), start=1):
        identifier = batch_id(index)
        batch_input_path = output_dir / f"batch-{identifier}.input.json"
        batch_result_path = output_dir / f"batch-{identifier}.result.json"
        batch_payload = {
            "mode": "arxiv-enrich-agent-completion",
            "batch": {
                "batch_id": identifier,
                "batch_index": index,
                "batch_count": 0,
                "recommended_worker": "arxiv-enrich-agent-completion",
            },
            "task_count": len(batch_tasks),
            "tasks": batch_tasks,
        }
        save_json(batch_input_path, batch_payload)
        batch_records.append(
            {
                "batch_id": identifier,
                "batch_index": index,
                "input_path": batch_input_path.name,
                "result_path": batch_result_path.name,
                "arxiv_ids": [str(task.get("arxiv_id") or "") for task in batch_tasks],
                "item_count": len(batch_tasks),
            }
        )

    total_batches = len(batch_records)
    for record in batch_records:
        batch_input_path = output_dir / str(record["input_path"])
        batch_payload = load_json(batch_input_path)
        batch_payload["batch"]["batch_count"] = total_batches
        save_json(batch_input_path, batch_payload)

    manifest = {
        "mode": "arxiv-enrich-agent-completion",
        "input_path": str(input_path),
        "batch_size": batch_size,
        "batch_count": total_batches,
        "item_count": len(tasks),
        "batches": batch_records,
    }
    save_json(output_dir / "manifest.json", manifest)
    log(
        "planned-enrich-batches",
        output_dir=str(output_dir),
        batch_count=total_batches,
        item_count=len(tasks),
        batch_size=batch_size,
    )
    return manifest


def _load_arxiv_enrich_module():
    module_path = Path(__file__).resolve().parents[1] / "arxiv-enrich" / "arxiv_enrich.py"
    spec = importlib.util.spec_from_file_location("followhub_arxiv_enrich", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def merge_enrich_results(*, input_path: Path, batch_dir: Path, output_path: Path) -> Dict[str, Any]:
    payload = load_json(input_path)
    manifest = load_manifest(batch_dir)
    agent_completion = payload.get("agent_completion") or {}
    tasks = list(agent_completion.get("tasks") or [])
    expected_ids = {str(task.get("arxiv_id") or "") for task in tasks}
    entries_by_id = {str(entry.get("id") or ""): dict(entry) for entry in (payload.get("entries") or [])}

    merged_rows: Dict[str, Dict[str, Any]] = {}
    for batch in manifest.get("batches") or []:
        result_path = batch_dir / str(batch.get("result_path") or "")
        if not result_path.exists():
            fail(f"Missing batch result: {result_path}")
        items = normalize_result_items(load_json(result_path))
        batch_ids = set(batch.get("arxiv_ids") or [])
        for item in items:
            arxiv_id = str(item.get("arxiv_id") or "")
            if arxiv_id not in expected_ids:
                fail(f"enrich batch result contains unknown arxiv_id: {arxiv_id}")
            if arxiv_id not in batch_ids:
                fail(f"enrich batch result contains arxiv_id outside its assigned batch: {arxiv_id}")
            if arxiv_id in merged_rows:
                fail(f"Duplicate enrich result for arxiv_id: {arxiv_id}")
            merged_rows[arxiv_id] = dict(item)
    missing = sorted(expected_ids - set(merged_rows))
    if missing:
        fail(f"Missing enrich completion rows for {len(missing)} task papers.")

    for arxiv_id, row in merged_rows.items():
        entry = entries_by_id.get(arxiv_id)
        if entry is None:
            fail(f"enrich_results entries do not contain task arxiv_id: {arxiv_id}")
        if "one_liner_zh" in row:
            entry["one_liner_zh"] = str(row.get("one_liner_zh") or "").strip()
        if "summary_cn" in row:
            entry["summary_cn"] = str(row.get("summary_cn") or "").strip()
        if "related_organizations" in row and isinstance(row.get("related_organizations"), list):
            entry["related_organizations"] = [str(item).strip() for item in (row.get("related_organizations") or []) if str(item).strip()]
        if "related_companies" in row and isinstance(row.get("related_companies"), list):
            entry["related_companies"] = [str(item).strip() for item in (row.get("related_companies") or []) if str(item).strip()]
        entry["needs_summary_cn_translation"] = not bool(str(entry.get("summary_cn") or "").strip())
        entry["needs_one_liner_zh"] = not bool(str(entry.get("one_liner_zh") or "").strip())
        entry["needs_agent_summary"] = bool(entry["needs_summary_cn_translation"] or entry["needs_one_liner_zh"])
        entry["needs_related_organizations"] = not bool(list(entry.get("related_organizations") or []))
        if not entry["needs_summary_cn_translation"]:
            entry["agent_translation_prompt"] = ""
        if not entry["needs_one_liner_zh"]:
            entry["agent_one_liner_prompt"] = ""
        if not entry["needs_agent_summary"]:
            entry["agent_summary_prompt"] = ""
        if not entry["needs_related_organizations"]:
            entry["agent_organization_prompt"] = ""

    payload["entries"] = list(entries_by_id.values())
    enrich_module = _load_arxiv_enrich_module()
    payload["agent_completion"] = enrich_module.build_agent_completion(payload["entries"])
    save_json(output_path, payload)
    log(
        "merged-enrich-results",
        output_path=str(output_path),
        completed_count=len(merged_rows),
        remaining_task_count=int((payload.get("agent_completion") or {}).get("task_count", 0) or 0),
    )
    return payload


def status(batch_dir: Path) -> Dict[str, Any]:
    manifest = load_manifest(batch_dir)
    batches = list(manifest.get("batches") or [])
    completed = 0
    pending = []
    for batch in batches:
        result_path = batch_dir / str(batch.get("result_path") or "")
        if result_path.exists():
            completed += 1
        else:
            pending.append(str(batch.get("batch_id") or ""))
    payload = {
        "mode": str(manifest.get("mode") or ""),
        "batch_count": len(batches),
        "completed_batch_count": completed,
        "pending_batch_count": len(batches) - completed,
        "pending_batch_ids": pending,
    }
    log("batch-status", **payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-agent-batch-runner")
    subparsers = parser.add_subparsers(dest="command")

    for command_name in ("plan-prefilter", "plan-filter"):
        cmd = subparsers.add_parser(command_name)
        cmd.add_argument("--input", required=True)
        cmd.add_argument("--output-dir", required=True)
        cmd.add_argument("--batch-size", type=int)

    for command_name in ("merge-prefilter", "merge-filter"):
        cmd = subparsers.add_parser(command_name)
        cmd.add_argument("--input", required=True)
        cmd.add_argument("--batch-dir", required=True)
        cmd.add_argument("--output", required=True)

    plan_enrich = subparsers.add_parser("plan-enrich")
    plan_enrich.add_argument("--input", required=True)
    plan_enrich.add_argument("--output-dir", required=True)
    plan_enrich.add_argument("--batch-size", type=int)

    merge_enrich = subparsers.add_parser("merge-enrich")
    merge_enrich.add_argument("--input", required=True)
    merge_enrich.add_argument("--batch-dir", required=True)
    merge_enrich.add_argument("--output", required=True)

    status_cmd = subparsers.add_parser("status")
    status_cmd.add_argument("--batch-dir", required=True)
    return parser


def main(argv: List[str] | None = None) -> int:
    argv = list(argv or [])
    if not argv:
        import sys

        argv = sys.argv[1:]
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    args = build_parser().parse_args(argv)
    if args.command == "plan-prefilter":
        plan_entry_batches(
            input_path=Path(args.input),
            output_dir=Path(args.output_dir),
            mode="title-prefilter",
            batch_mode="arxiv-title-prefilter",
            fallback_batch_size=10,
            batch_size_override=args.batch_size,
        )
        return 0
    if args.command == "merge-prefilter":
        merge_prefilter_results(
            input_path=Path(args.input),
            batch_dir=Path(args.batch_dir),
            output_path=Path(args.output),
        )
        return 0
    if args.command == "plan-filter":
        plan_entry_batches(
            input_path=Path(args.input),
            output_dir=Path(args.output_dir),
            mode="filter",
            batch_mode="arxiv-filter-batches",
            fallback_batch_size=5,
            batch_size_override=args.batch_size,
        )
        return 0
    if args.command == "merge-filter":
        merge_filter_results(
            input_path=Path(args.input),
            batch_dir=Path(args.batch_dir),
            output_path=Path(args.output),
        )
        return 0
    if args.command == "plan-enrich":
        plan_enrich_batches(
            input_path=Path(args.input),
            output_dir=Path(args.output_dir),
            batch_size_override=args.batch_size,
        )
        return 0
    if args.command == "merge-enrich":
        merge_enrich_results(
            input_path=Path(args.input),
            batch_dir=Path(args.batch_dir),
            output_path=Path(args.output),
        )
        return 0
    if args.command == "status":
        status(Path(args.batch_dir))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
