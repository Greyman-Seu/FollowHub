#!/usr/bin/env python3
"""Verify required publish artifacts for RSS daily output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


HELP_TEXT = """\
rss-verify: Verify published RSS daily artifacts.

Usage:
    rss-verify help
    rss-verify verify --publish-dir rss-daily-output/2026-05-12/publish-out --date 2026-05-12 --output rss-daily-output/2026-05-12/verify.json
"""


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_story_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    stories = payload.get("stories")
    if isinstance(stories, list) and stories:
        return [item for item in stories if isinstance(item, dict)]
    items: List[Dict[str, Any]] = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def validate_digest_payload(payload: Dict[str, Any], digest_date: str) -> Dict[str, Any]:
    issues: List[str] = []
    required_top_level = ["date", "summary", "highlights", "counts"]
    for key in required_top_level:
        if key not in payload:
            issues.append(f"Digest is missing top-level field: {key}")
    if str(payload.get("date") or "") != digest_date:
        issues.append(f"Digest date does not match requested date: {payload.get('date')!r} != {digest_date!r}")

    stories = payload.get("stories")
    sections = payload.get("sections")
    if stories is not None and not isinstance(stories, list):
        issues.append("Digest stories field must be a list when present.")
        stories = []
    if not isinstance(sections, list):
        issues.append("Digest sections field must be a list.")
        sections = []

    story_items = collect_story_items(payload)
    seen_item_ids = set()
    for index, item in enumerate(story_items):
        item_id = str(item.get("story_id") or item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not item_id:
            issues.append(f"Story item {index} is missing story identity.")
        elif item_id in seen_item_ids:
            issues.append(f"Duplicate top-level story identity found in digest: {item_id}")
        else:
            seen_item_ids.add(item_id)
        if not title:
            issues.append(f"Story item {index} is missing title.")
        if not summary:
            issues.append(f"Story item {index} is missing summary.")
        if stories and "story_status" not in item:
            issues.append(f"Story item {index} is missing story_status.")
        if "representative_item_id" not in item and "id" not in item and "story_id" not in item:
            issues.append(f"Story item {index} is missing representative item identity.")

    section_total = 0
    computed_counts: Dict[str, int] = {}
    for index, section in enumerate(sections):
        source_type = str(section.get("source_type") or "").strip()
        items = section.get("items")
        declared_count = int(section.get("count") or 0)
        if not source_type:
            issues.append(f"Section {index} is missing source_type.")
        if not isinstance(items, list):
            issues.append(f"Section {index} items must be a list.")
            continue
        if declared_count != len(items):
            issues.append(f"Section {index} declared count does not match item count: {declared_count} != {len(items)}")
        section_total += len(items)
        if source_type:
            computed_counts[source_type] = computed_counts.get(source_type, 0) + len(items)
    if isinstance(stories, list) and stories and section_total and len(stories) != section_total:
        issues.append(f"Digest stories count does not match section item count: {len(stories)} != {section_total}")

    counts = payload.get("counts")
    if isinstance(counts, dict):
        for source_type, item_count in computed_counts.items():
            declared = int(counts.get(source_type) or 0)
            if declared != item_count:
                issues.append(f"Counts mismatch for source {source_type!r}: {declared} != {item_count}")

    return {
        "story_count": len(story_items),
        "section_count": len(sections),
        "issues": issues,
        "ok": not issues,
    }


def verify_paths(publish_dir: Path, digest_date: str) -> Dict[str, Any]:
    required = [
        publish_dir / "latest.json",
        publish_dir / "daily" / f"{digest_date}.json",
        publish_dir / "manifest.json",
    ]
    missing: List[str] = [str(path) for path in required if not path.exists()]
    source_dir = publish_dir / "sources"
    source_files = sorted(str(path.relative_to(publish_dir)) for path in source_dir.glob("*.json")) if source_dir.exists() else []
    if not source_files:
        missing.append(str(source_dir / "*.json"))
    content_checks: Dict[str, Any] = {"ok": False, "issues": ["Skipped because required files are missing."], "story_count": 0, "section_count": 0}
    daily_digest_path = publish_dir / "daily" / f"{digest_date}.json"
    if not missing and daily_digest_path.exists():
        try:
            payload = load_json(daily_digest_path)
            content_checks = validate_digest_payload(payload, digest_date)
        except Exception as exc:
            content_checks = {
                "ok": False,
                "issues": [f"Failed to parse digest content: {exc}"],
                "story_count": 0,
                "section_count": 0,
            }
    return {
        "date": digest_date,
        "publish_dir": str(publish_dir),
        "required_checks": [str(path.relative_to(publish_dir)) for path in required] + ["sources/*.json"],
        "source_files": source_files,
        "missing": missing,
        "content_checks": content_checks,
        "ok": (not missing) and bool(content_checks.get("ok", False)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-verify")
    subparsers = parser.add_subparsers(dest="command")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--publish-dir", required=True)
    verify.add_argument("--date", required=True)
    verify.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if not argv:
        import sys

        argv = sys.argv[1:]
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        payload = verify_paths(Path(args.publish_dir), args.date)
        save_json(Path(args.output), payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
