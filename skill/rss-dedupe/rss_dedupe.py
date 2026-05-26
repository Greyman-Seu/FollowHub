#!/usr/bin/env python3
"""Deterministically deduplicate same-content RSS items."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse, urlunparse


HELP_TEXT = """\
rss-dedupe: Deduplicate same-content RSS items.

Usage:
    rss-dedupe help
    rss-dedupe dedupe --input rss-daily-output/2026-05-12/fetch/fetched_items.json --output rss-daily-output/2026-05-12/dedupe/deduped_items.json
"""

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "feature",
    "src",
    "spm",
    "from",
}
WECHAT_ARTICLE_PAT = re.compile(r"/s\b", re.IGNORECASE)
X_STATUS_PAT = re.compile(r"/status/(\d+)", re.IGNORECASE)
ARXIV_PAT = re.compile(r"arxiv\.org/(abs|pdf)/([0-9.]+)", re.IGNORECASE)
GITHUB_REPO_PAT = re.compile(r"github\.com/([^/]+/[^/?#]+)", re.IGNORECASE)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    kept = []
    for key in sorted(query):
        if key.lower() in TRACKING_QUERY_KEYS:
            continue
        for item in query[key]:
            kept.append((key, item))
    query_string = "&".join(f"{key}={item}" if item else key for key, item in kept)
    normalized = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
        query=query_string,
    )
    return urlunparse(normalized)


def canonical_id_for_url(source_type: str, url: str) -> str:
    normalized = normalize_url(url)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    host = parsed.netloc.lower()

    if "mp.weixin.qq.com" in host and WECHAT_ARTICLE_PAT.search(parsed.path):
        biz = (query.get("__biz") or [""])[0]
        mid = (query.get("mid") or [""])[0]
        idx = (query.get("idx") or [""])[0]
        sn = (query.get("sn") or [""])[0]
        if biz and mid:
            return f"wechat:{biz}:{mid}:{idx}:{sn}"

    match = X_STATUS_PAT.search(parsed.path)
    if host.endswith("x.com") or host.endswith("twitter.com"):
        if match:
            return f"x-status:{match.group(1)}"

    match = ARXIV_PAT.search(normalized)
    if match:
        return f"arxiv:{match.group(2)}"

    match = GITHUB_REPO_PAT.search(normalized)
    if match:
        return f"github:{match.group(1).lower()}"

    return f"url:{normalized}"


def content_fingerprint(item: Dict[str, Any]) -> str:
    title = " ".join(str(item.get("title") or "").lower().split())
    author = " ".join(str(item.get("author") or "").lower().split())
    published = str(item.get("published_at") or "")[:10]
    if title:
        return f"title:{title}|author:{author}|day:{published}"
    return ""


def dedupe_key(item: Dict[str, Any]) -> Tuple[str, str]:
    source_type = str(item.get("source_type") or "rss").strip() or "rss"
    url = str(item.get("url") or item.get("link") or "").strip()
    canonical = canonical_id_for_url(source_type, url)
    if canonical:
        return canonical, "url"
    fingerprint = content_fingerprint(item)
    if fingerprint:
        return f"fingerprint:{fingerprint}", "fingerprint"
    return str(item.get("id") or "").strip(), "raw-id"


def choose_representative(current: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    current_text = len(str(current.get("content_text") or ""))
    incoming_text = len(str(incoming.get("content_text") or ""))
    if incoming_text > current_text:
        return incoming
    if str(incoming.get("published_at") or "") < str(current.get("published_at") or ""):
        return incoming
    return current


def dedupe_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    duplicates: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        entry = dict(item)
        normalized_url = normalize_url(str(entry.get("url") or entry.get("link") or ""))
        entry["normalized_url"] = normalized_url
        entry["origin_url"] = normalized_url or str(entry.get("url") or "")
        canonical_id, match_kind = dedupe_key(entry)
        entry["canonical_id"] = canonical_id or str(entry.get("id") or "")
        entry["dedupe_match_kind"] = match_kind
        current = grouped.get(entry["canonical_id"])
        duplicates.setdefault(entry["canonical_id"], []).append(entry)
        if current is None:
            grouped[entry["canonical_id"]] = entry
        else:
            grouped[entry["canonical_id"]] = choose_representative(current, entry)

    deduped_items: List[Dict[str, Any]] = []
    for canonical_id, representative in grouped.items():
        related = duplicates.get(canonical_id, [])
        representative = dict(representative)
        representative["duplicate_count"] = max(0, len(related) - 1)
        representative["duplicate_items"] = [
            {
                "id": str(item.get("id") or ""),
                "source_name": str(item.get("source_name") or ""),
                "source_type": str(item.get("source_type") or ""),
                "url": str(item.get("url") or ""),
                "published_at": str(item.get("published_at") or ""),
            }
            for item in related
            if str(item.get("id") or "") != str(representative.get("id") or "")
        ]
        deduped_items.append(representative)
    deduped_items.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    return {
        "mode": "rss-deduped",
        "item_count": len(deduped_items),
        "input_item_count": len(items),
        "items": deduped_items,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-dedupe")
    subparsers = parser.add_subparsers(dest="command")
    dedupe = subparsers.add_parser("dedupe")
    dedupe.add_argument("--input", required=True)
    dedupe.add_argument("--output", required=True)
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
    if args.command == "dedupe":
        payload = load_json(Path(args.input))
        result = dedupe_items(list(payload.get("items") or []))
        save_json(Path(args.output), result)
        print(json.dumps({"mode": "rss-deduped", "output": args.output, "item_count": result["item_count"]}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
