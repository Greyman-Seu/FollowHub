#!/usr/bin/env python3
"""Cluster deduped RSS items into lightweight stories."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


HELP_TEXT = """\
rss-cluster: Group deduped RSS items into stories.

Usage:
    rss-cluster help
    rss-cluster cluster --input rss-daily-output/2026-05-12/dedupe/deduped_items.json --output rss-daily-output/2026-05-12/cluster/clustered_items.json
"""

TOKEN_PAT = re.compile(r"[a-z0-9][a-z0-9._/-]+", re.IGNORECASE)
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "about",
    "this",
    "that",
    "what",
    "when",
    "your",
    "will",
    "have",
    "after",
    "using",
    "wechat",
    "twitter",
}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_tokens(title: str, content_text: str) -> List[str]:
    merged = f"{title} {content_text[:400]}".lower()
    tokens = []
    seen = set()
    for match in TOKEN_PAT.finditer(merged):
        token = match.group(0).strip("._/-")
        if len(token) < 4 or token in STOPWORDS or token.isdigit():
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens[:6]


def derive_story_id(item: Dict[str, Any]) -> str:
    canonical_id = str(item.get("canonical_id") or "")
    if canonical_id.startswith(("arxiv:", "github:", "x-status:", "wechat:")):
        return f"story:{canonical_id}"
    tokens = extract_tokens(str(item.get("title") or ""), str(item.get("content_text") or ""))
    day = str(item.get("published_at") or "")[:10]
    if tokens:
        return "story:" + "-".join(tokens[:3]) + (f":{day}" if day else "")
    item_id = str(item.get("id") or "")
    return f"story:item:{item_id}"


def classify_status(
    item: Dict[str, Any],
    *,
    primary_canonical_id: str,
    distinct_canonical_ids: List[str],
    primary_item_id: str,
) -> str:
    duplicate_count = int(item.get("duplicate_count") or 0)
    if duplicate_count > 0:
        return "repeat"

    canonical_id = str(item.get("canonical_id") or "")
    item_id = str(item.get("id") or "")
    if len(distinct_canonical_ids) > 1:
        if canonical_id and canonical_id != primary_canonical_id:
            return "followup"
        if not canonical_id and item_id != primary_item_id:
            return "followup"

    return "new"


def build_agent_handoff(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks = []
    for item in items:
        if str(item.get("story_match_confidence") or "") != "low":
            continue
        tasks.append(
            {
                "id": str(item.get("id") or ""),
                "story_id": str(item.get("story_id") or ""),
                "title": str(item.get("title") or ""),
                "question": "Decide whether this item should merge into an existing story or stay isolated.",
                "context": {
                    "canonical_id": str(item.get("canonical_id") or ""),
                    "tokens": list(item.get("story_tokens") or []),
                },
            }
        )
    return {
        "required": bool(tasks),
        "task_count": len(tasks),
        "recommended_batch_size": 3,
        "recommended_worker": "rss-cluster-agent-review",
        "tasks": tasks,
    }


def cluster_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    story_groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        row = dict(item)
        story_tokens = extract_tokens(str(row.get("title") or ""), str(row.get("content_text") or ""))
        row["story_tokens"] = story_tokens
        row["story_id"] = derive_story_id(row)
        row["story_match_confidence"] = "high" if row["story_id"].startswith("story:arxiv:") or row["story_id"].startswith("story:x-status:") or row["story_id"].startswith("story:wechat:") else ("medium" if story_tokens else "low")
        story_groups.setdefault(row["story_id"], []).append(row)

    story_index = []
    enriched_items: List[Dict[str, Any]] = []
    for story_id, grouped in story_groups.items():
        ordered_group = sorted(
            grouped,
            key=lambda item: (
                str(item.get("published_at") or ""),
                str(item.get("id") or ""),
            ),
        )
        primary_item = ordered_group[0]
        primary_item_id = str(primary_item.get("id") or "")
        distinct_canonical_ids: List[str] = []
        for item in ordered_group:
            canonical_id = str(item.get("canonical_id") or "")
            if canonical_id and canonical_id not in distinct_canonical_ids:
                distinct_canonical_ids.append(canonical_id)
        primary_canonical_id = distinct_canonical_ids[0] if distinct_canonical_ids else ""

        normalized_group = []
        for item in ordered_group:
            row = dict(item)
            row["story_status"] = classify_status(
                row,
                primary_canonical_id=primary_canonical_id,
                distinct_canonical_ids=distinct_canonical_ids,
                primary_item_id=primary_item_id,
            )
            normalized_group.append(row)
            enriched_items.append(row)

        representative = sorted(
            normalized_group,
            key=lambda item: (
                len(str(item.get("content_text") or "")),
                -int(item.get("duplicate_count") or 0),
                str(item.get("published_at") or ""),
            ),
            reverse=True,
        )[0]
        sources = []
        source_names = []
        for item in normalized_group:
            source_type = str(item.get("source_type") or "")
            source_name = str(item.get("source_name") or "")
            if source_type and source_type not in sources:
                sources.append(source_type)
            if source_name and source_name not in source_names:
                source_names.append(source_name)
        story_index.append(
            {
                "story_id": story_id,
                "story_status": str(representative.get("story_status") or "new"),
                "representative_item_id": str(representative.get("id") or ""),
                "title": str(representative.get("title") or ""),
                "mention_count": len(normalized_group) + int(representative.get("duplicate_count") or 0),
                "source_types": sources,
                "source_names": source_names,
                "first_seen_at": min(str(item.get("published_at") or "") for item in normalized_group),
                "last_seen_at": max(str(item.get("published_at") or "") for item in normalized_group),
            }
        )
    story_index.sort(key=lambda item: item["last_seen_at"], reverse=True)
    return {
        "mode": "rss-clustered",
        "item_count": len(enriched_items),
        "story_count": len(story_index),
        "items": enriched_items,
        "stories": story_index,
        "agent_handoff": build_agent_handoff(enriched_items),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-cluster")
    subparsers = parser.add_subparsers(dest="command")
    cluster = subparsers.add_parser("cluster")
    cluster.add_argument("--input", required=True)
    cluster.add_argument("--output", required=True)
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
    if args.command == "cluster":
        payload = load_json(Path(args.input))
        result = cluster_items(list(payload.get("items") or []))
        save_json(Path(args.output), result)
        print(json.dumps({"mode": "rss-clustered", "output": args.output, "story_count": result["story_count"]}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
