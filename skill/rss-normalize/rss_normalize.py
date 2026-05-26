#!/usr/bin/env python3
"""Normalize raw RSS items into a shared content contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


HELP_TEXT = """\
rss-normalize: Normalize raw RSS items.

Usage:
    rss-normalize help
    rss-normalize normalize --input rss-collect-output/raw.json --output rss-daily-output/2026-05-12/normalize/normalized_items.json
"""


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for item in items:
        source_type = str(item.get("source_type") or "rss").strip() or "rss"
        source_name = str(item.get("source_name") or "").strip()
        normalized.append(
            {
                "id": str(item.get("id") or ""),
                "source_type": source_type,
                "source_name": source_name,
                "title": str(item.get("title") or ""),
                "author": str(item.get("author") or ""),
                "published_at": str(item.get("published_at") or ""),
                "url": str(item.get("link") or item.get("url") or ""),
                "content_text": str(item.get("content_text") or ""),
                "summary": str(item.get("summary") or ""),
                "tags": list(item.get("tags") or []),
                "raw_meta": dict(item.get("raw_meta") or {}),
            }
        )
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-normalize")
    subparsers = parser.add_subparsers(dest="command")
    normalize = subparsers.add_parser("normalize")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
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
    if args.command == "normalize":
        payload = load_json(Path(args.input))
        items = normalize_items(list(payload.get("items") or []))
        result = {
            "mode": "rss-normalized",
            "item_count": len(items),
            "items": items,
        }
        save_json(Path(args.output), result)
        print(json.dumps({"mode": "rss-normalized", "output": args.output, "item_count": len(items)}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
