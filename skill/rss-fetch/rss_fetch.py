#!/usr/bin/env python3
"""Fetch or preserve content for normalized RSS items."""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


HELP_TEXT = """\
rss-fetch: Fetch full content for normalized RSS items.

Usage:
    rss-fetch help
    rss-fetch fetch --input rss-daily-output/2026-05-12/normalize/normalized_items.json --output rss-daily-output/2026-05-12/fetch/fetched_items.json
"""

SCRIPT_TAG_PAT = re.compile(r"<script\\b.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_TAG_PAT = re.compile(r"<style\\b.*?</style>", re.IGNORECASE | re.DOTALL)
TAG_PAT = re.compile(r"<[^>]+>")
WS_PAT = re.compile(r"\\s+")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "followhub-rss-fetch/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def html_to_text(raw_html: str) -> str:
    text = SCRIPT_TAG_PAT.sub(" ", raw_html or "")
    text = STYLE_TAG_PAT.sub(" ", text)
    text = TAG_PAT.sub(" ", text)
    text = html.unescape(text)
    text = WS_PAT.sub(" ", text).strip()
    return text


def fetch_item_content(item: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(item)
    existing = str(item.get("content_text") or "").strip()
    summary = str(item.get("summary") or "").strip()
    url = str(item.get("url") or item.get("link") or "").strip()
    if existing:
        row["content_text"] = existing
        row["fetch_status"] = "preserved"
        return row
    if not url:
        row["content_text"] = summary
        row["fetch_status"] = "fallback-summary"
        return row
    try:
        raw_html = fetch_text(url)
        text = html_to_text(raw_html)
    except Exception:
        row["content_text"] = summary
        row["fetch_status"] = "fallback-summary"
        return row
    row["content_text"] = text or summary
    row["fetch_status"] = "fetched-html" if text else "fallback-summary"
    return row


def fetch_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [fetch_item_content(item) for item in items]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-fetch")
    subparsers = parser.add_subparsers(dest="command")
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output", required=True)
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
    if args.command == "fetch":
        payload = load_json(Path(args.input))
        items = fetch_items(list(payload.get("items") or []))
        result = {"mode": "rss-fetched", "item_count": len(items), "items": items}
        save_json(Path(args.output), result)
        print(json.dumps({"mode": "rss-fetched", "output": args.output, "item_count": len(items)}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
