#!/usr/bin/env python3
"""Build a daily digest from enriched RSS items."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


HELP_TEXT = """\
rss-digest: Build the RSS daily digest.

Usage:
    rss-digest help
    rss-digest build --input rss-daily-output/2026-05-12/enrich_results.json --output rss-daily-output/2026-05-12/daily-digest.json
"""


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_digest(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    selected = [entry for entry in entries if bool(entry.get("include_in_digest", True))]
    grouped = defaultdict(list)
    for entry in selected:
        story_id = str(entry.get("story_id") or str(entry.get("id") or ""))
        grouped[story_id].append(dict(entry))

    story_items = []
    for story_id, story_entries in grouped.items():
        representative = sorted(
            story_entries,
            key=lambda item: (
                len(str(item.get("summary_cn") or "")),
                len(str(item.get("content_text") or "")),
                str(item.get("published_at") or ""),
            ),
            reverse=True,
        )[0]
        source_type = str(representative.get("source_type") or "rss")
        source_name = str(representative.get("source_name") or "")
        first_seen_at = min(str(item.get("published_at") or "") for item in story_entries)
        last_seen_at = max(str(item.get("published_at") or "") for item in story_entries)
        source_types: List[str] = []
        source_names: List[str] = []
        for item in story_entries:
            item_source_type = str(item.get("source_type") or "rss")
            item_source_name = str(item.get("source_name") or "")
            if item_source_type and item_source_type not in source_types:
                source_types.append(item_source_type)
            if item_source_name and item_source_name not in source_names:
                source_names.append(item_source_name)
        source_type = str(representative.get("source_type") or "rss")
        story_items.append(
            {
                "id": str(representative.get("id") or ""),
                "story_id": story_id,
                "story_status": str(representative.get("story_status") or "new"),
                "representative_item_id": str(representative.get("id") or ""),
                "source_type": source_type,
                "source_name": source_name,
                "title": str(representative.get("title") or ""),
                "summary": str(representative.get("one_liner_zh") or representative.get("title") or ""),
                "one_liner_zh": str(representative.get("one_liner_zh") or ""),
                "summary_cn": str(representative.get("summary_cn") or ""),
                "domains": list(representative.get("domains") or []),
                "related_organizations": list(representative.get("related_organizations") or []),
                "related_companies": list(representative.get("related_companies") or []),
                "key_people": list(representative.get("key_people") or []),
                "url": str(representative.get("url") or ""),
                "published_at": str(representative.get("published_at") or ""),
                "canonical_id": str(representative.get("canonical_id") or ""),
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "source_types": source_types,
                "source_names": source_names,
                "mention_count": len(story_entries) + int(representative.get("duplicate_count") or 0),
                "related_items": [
                    {
                        "id": str(item.get("id") or ""),
                        "source_name": str(item.get("source_name") or ""),
                        "source_type": str(item.get("source_type") or ""),
                        "published_at": str(item.get("published_at") or ""),
                        "url": str(item.get("url") or ""),
                    }
                    for item in story_entries
                    if str(item.get("id") or "") != str(representative.get("id") or "")
                ]
                + list(representative.get("duplicate_items") or []),
            }
        )

    items = sorted(story_items, key=lambda item: str(item.get("last_seen_at") or item.get("published_at") or ""), reverse=True)
    highlights = [item["summary"] for item in items[:3]]
    sections = []
    counts = {"arxiv": 0, "wechat": 0, "x": 0, "bilibili": 0, "rss": 0}
    grouped_by_source = defaultdict(list)
    for item in items:
        grouped_by_source[str(item.get("source_type") or "rss")].append(item)
    for source_type, source_items in grouped_by_source.items():
        sections.append(
            {
                "source_type": source_type,
                "title": source_type,
                "count": len(source_items),
                "items": source_items,
            }
        )
        if source_type in counts:
            counts[source_type] = len(source_items)
    return {
        "summary": f"Selected {len(items)} RSS stories for today.",
        "highlights": highlights,
        "counts": counts,
        "stories": items,
        "sections": sections,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-digest")
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build")
    build.add_argument("--input", required=True)
    build.add_argument("--output", required=True)
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
    if args.command == "build":
        payload = load_json(Path(args.input))
        digest = build_digest(list(payload.get("entries") or []))
        save_json(Path(args.output), digest)
        total_count = sum(int(value or 0) for value in (digest.get("counts") or {}).values())
        print(json.dumps({"mode": "rss-digest", "output": args.output, "count": total_count}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
