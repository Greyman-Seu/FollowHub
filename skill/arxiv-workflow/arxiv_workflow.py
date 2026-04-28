#!/usr/bin/env python3
"""
arxiv_workflow.py - Agent-facing orchestrator for the FollowHub arXiv pipeline.
"""

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence


HELP_TEXT = """\
arxiv-workflow: Compose arxiv-find results into a viewer and enrich work plan.

Usage:
    arxiv-workflow help
    arxiv-workflow compose --input /path/to/arxiv-find-output --workspace ./workflow-out [--selected-ids 2604.1,2604.2]
"""


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_view_module():
    path = Path(__file__).resolve().parents[1] / "arxiv-view" / "arxiv_view.py"
    if not path.exists():
        raise RuntimeError(f"Missing arxiv-view module: {path}")
    return _load_module(path, "followhub_arxiv_view")


def split_ids(raw: str) -> List[str]:
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def _balanced_group_count(total_ids: int) -> int:
    if total_ids <= 5:
        return total_ids
    lower = math.ceil(total_ids / 5)
    upper = math.ceil(total_ids / 3)
    best = lower
    best_delta = None
    for groups in range(lower, upper + 1):
        avg = total_ids / groups
        if 3 <= avg <= 5:
            delta = abs(avg - 4)
            if best_delta is None or delta < best_delta:
                best = groups
                best_delta = delta
    return best


def _balanced_groups(ids: List[str]) -> List[List[str]]:
    if len(ids) <= 5:
        return [[item] for item in ids]

    group_count = _balanced_group_count(len(ids))
    base = len(ids) // group_count
    remainder = len(ids) % group_count
    groups: List[List[str]] = []
    cursor = 0
    for index in range(group_count):
        size = base + (1 if index < remainder else 0)
        groups.append(ids[cursor : cursor + size])
        cursor += size
    return groups


def plan_enrich_batches(selected_ids: List[str]) -> Dict[str, object]:
    ids = [item for item in selected_ids if item]
    if len(ids) <= 1:
        return {
            "mode": "inline",
            "groups": [ids] if ids else [],
            "worker_skill": "arxiv-enrich",
        }
    if len(ids) <= 5:
        return {
            "mode": "subagent",
            "groups": [[item] for item in ids],
            "worker_skill": "arxiv-enrich",
        }
    return {
        "mode": "subagent",
        "groups": _balanced_groups(ids),
        "worker_skill": "arxiv-enrich",
    }


def compose_from_result(
    *,
    input_path: Path,
    workspace: Path,
    selected_ids: Optional[List[str]] = None,
) -> Dict[str, object]:
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    view_dir = workspace / "view"
    view_module = load_view_module()
    normalized = view_module.build_bundle(input_path=Path(input_path), output_dir=view_dir)
    available_ids = [item["arxiv_id"] for item in normalized["items"]]
    selected = selected_ids or available_ids
    selected = [item for item in selected if item in available_ids]

    manifest = {
        "result_mode": normalized["mode"],
        "title": normalized["title"],
        "subtitle": normalized["subtitle"],
        "item_count": normalized["meta"].get("item_count", len(normalized["items"])),
        "days": normalized["meta"].get("days", []),
        "input_path": str(Path(input_path)),
        "viewer_dir": str(view_dir),
        "viewer_entry": str(view_dir / "index.html"),
        "data_path": str(view_dir / "data.json"),
        "selected_ids": selected,
        "enrich_plan": plan_enrich_batches(selected),
    }

    with open(workspace / "workflow.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-workflow")
    subparsers = parser.add_subparsers(dest="command")

    compose = subparsers.add_parser("compose")
    compose.add_argument("--input", required=True)
    compose.add_argument("--workspace", required=True)
    compose.add_argument("--selected-ids")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "compose":
        manifest = compose_from_result(
            input_path=Path(args.input),
            workspace=Path(args.workspace),
            selected_ids=split_ids(args.selected_ids) if args.selected_ids else None,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
