#!/usr/bin/env python3
"""Fetch or preserve content for normalized RSS items."""

from __future__ import annotations

import argparse
import concurrent.futures
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
    rss-fetch fetch --input rss-daily-output/2026-05-12/normalize/normalized_items.json --output rss-daily-output/2026-05-12/fetch/fetched_items.json --max-workers 8 --request-timeout-seconds 30
"""

SCRIPT_TAG_PAT = re.compile(r"<script\\b.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_TAG_PAT = re.compile(r"<style\\b.*?</style>", re.IGNORECASE | re.DOTALL)
TAG_PAT = re.compile(r"<[^>]+>")
WS_PAT = re.compile(r"\\s+")
WECHAT_BLOCK_HINTS = ("环境异常", "去验证", "微信公众平台", "secitptpage/verify.html")


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


def clean_summary_text(value: str) -> str:
    return " ".join(html_to_text(value or "").split()).strip()


def looks_like_block_page(text: str) -> bool:
    body = str(text or "")
    return any(hint in body for hint in WECHAT_BLOCK_HINTS)


def fetch_item_content(item: Dict[str, Any], *, request_timeout_seconds: int = 30) -> Dict[str, Any]:
    row = dict(item)
    existing = str(item.get("content_text") or "").strip()
    summary = str(item.get("summary") or "").strip()
    cleaned_summary = clean_summary_text(summary)
    source_type = str(item.get("source_type") or "rss").strip().lower()
    url = str(item.get("url") or item.get("link") or "").strip()
    if existing:
        row["content_text"] = existing
        row["fetch_status"] = "preserved"
        return row
    if source_type in {"x", "wechat"} and cleaned_summary:
        row["content_text"] = cleaned_summary
        row["fetch_status"] = "preserved-summary"
        return row
    if not url:
        row["content_text"] = cleaned_summary or summary
        row["fetch_status"] = "fallback-summary"
        return row
    try:
        raw_html = fetch_text(url, timeout=request_timeout_seconds)
        text = html_to_text(raw_html)
    except Exception:
        row["content_text"] = cleaned_summary or summary
        row["fetch_status"] = "fallback-summary"
        return row
    if looks_like_block_page(raw_html) or looks_like_block_page(text):
        row["content_text"] = cleaned_summary or summary or str(item.get("title") or "").strip()
        row["fetch_status"] = "fallback-blocked"
        return row
    row["content_text"] = text or cleaned_summary or summary
    row["fetch_status"] = "fetched-html" if text else "fallback-summary"
    return row


def fetch_items(
    items: List[Dict[str, Any]],
    *,
    max_workers: int = 8,
    request_timeout_seconds: int = 30,
) -> List[Dict[str, Any]]:
    if max_workers <= 1 or len(items) <= 1:
        return [
            fetch_item_content(item, request_timeout_seconds=request_timeout_seconds)
            for item in items
        ]

    results: List[Dict[str, Any]] = [None] * len(items)  # type: ignore[list-item]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(
                fetch_item_content,
                item,
                request_timeout_seconds=request_timeout_seconds,
            ): index
            for index, item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-fetch")
    subparsers = parser.add_subparsers(dest="command")
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--max-workers", type=int, default=8)
    fetch.add_argument("--request-timeout-seconds", type=int, default=30)
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
        items = fetch_items(
            list(payload.get("items") or []),
            max_workers=max(1, int(args.max_workers)),
            request_timeout_seconds=max(1, int(args.request_timeout_seconds)),
        )
        result = {
            "mode": "rss-fetched",
            "item_count": len(items),
            "max_workers": max(1, int(args.max_workers)),
            "request_timeout_seconds": max(1, int(args.request_timeout_seconds)),
            "items": items,
        }
        save_json(Path(args.output), result)
        print(
            json.dumps(
                {
                    "mode": "rss-fetched",
                    "output": args.output,
                    "item_count": len(items),
                    "max_workers": max(1, int(args.max_workers)),
                    "request_timeout_seconds": max(1, int(args.request_timeout_seconds)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
