#!/usr/bin/env python3
"""Collect raw RSS entries into a shared raw bundle."""

from __future__ import annotations

import argparse
import email.utils
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


HELP_TEXT = """\
rss-collect: Collect raw RSS entries.

Usage:
    rss-collect help
    rss-collect collect --config followhub.yaml --output rss-collect-output/2026-05-12-raw.json
"""


class SourceConfig:
    def __init__(
        self,
        *,
        name: str,
        source_type: str,
        feed_url: str,
        enabled: bool = True,
        tags: Optional[List[str]] = None,
        max_items: Optional[int] = None,
    ) -> None:
        self.name = name
        self.source_type = source_type
        self.feed_url = feed_url
        self.enabled = enabled
        self.tags = tags
        self.max_items = max_items


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML is required to load rss config files.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Config file must contain a top-level mapping: {path}")
    return data


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_datetime(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_source(source: Dict[str, Any]) -> Optional[SourceConfig]:
    name = str(source.get("name") or "").strip()
    feed_url = str(source.get("feed_url") or "").strip()
    if not name or not feed_url:
        return None
    tags = [str(tag).strip() for tag in (source.get("tags") or []) if str(tag).strip()]
    max_items_raw = source.get("max_items")
    max_items = int(max_items_raw) if max_items_raw not in (None, "") else None
    return SourceConfig(
        name=name,
        source_type=str(source.get("type") or "rss").strip() or "rss",
        feed_url=feed_url,
        enabled=bool(source.get("enabled", True)),
        tags=tags,
        max_items=max_items,
    )


def load_source_file(path: Path) -> List[SourceConfig]:
    data = load_yaml(path)
    raw_sources: Iterable[Any]
    if isinstance(data.get("sources"), list):
        raw_sources = data.get("sources") or []
    elif isinstance(data.get("rss"), dict) and isinstance((data.get("rss") or {}).get("sources"), list):
        raw_sources = (data.get("rss") or {}).get("sources") or []
    else:
        raw_sources = []
    items: List[SourceConfig] = []
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        parsed = _coerce_source(source)
        if parsed is not None:
            items.append(parsed)
    return items


def load_sources(config_path: Path) -> List[SourceConfig]:
    config = load_yaml(config_path)
    rss = config.get("rss") or {}
    sources = rss.get("sources") if isinstance(rss, dict) else []
    source_files: List[Path] = []
    if isinstance(rss, dict):
        single = str(rss.get("sources_file") or "").strip()
        if single:
            source_files.append((config_path.parent / single).resolve())
        for item in rss.get("source_files") or []:
            value = str(item or "").strip()
            if value:
                source_files.append((config_path.parent / value).resolve())
    items: List[SourceConfig] = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        parsed = _coerce_source(source)
        if parsed is not None:
            items.append(parsed)
    for source_file in source_files:
        items.extend(load_source_file(source_file))
    deduped: List[SourceConfig] = []
    seen = set()
    for item in items:
        key = (item.source_type, item.name, item.feed_url)
        if key in seen:
            continue
        seen.add(key)
        if item.enabled:
            deduped.append(item)
    return deduped


def load_rss_settings(config_path: Path) -> Dict[str, Any]:
    config = load_yaml(config_path)
    rss = config.get("rss") or {}
    daily = rss.get("daily") if isinstance(rss, dict) else {}
    lookback_days = int((daily or {}).get("lookback_days") or 2) if isinstance(daily, dict) else 2
    max_items_per_source = int((daily or {}).get("max_items_per_source") or 50) if isinstance(daily, dict) else 50
    return {
        "lookback_days": lookback_days,
        "max_items_per_source": max_items_per_source,
    }


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "followhub-rss-collect/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _find_text(parent: ET.Element, paths: List[str]) -> str:
    for path in paths:
        node = parent.find(path, ATOM_NS)
        if node is not None and node.text:
            return _clean_text(node.text)
    return ""


def parse_rss_items(xml_text: str, source: SourceConfig) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: List[Dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        link = _find_text(item, ["link"])
        guid = _find_text(item, ["guid"]) or link
        published_raw = _find_text(item, ["pubDate"])
        items.append(
            {
                "id": f"{source.source_type}:{guid or link or _find_text(item, ['title'])}",
                "source_name": source.name,
                "source_type": source.source_type,
                "feed_url": source.feed_url,
                "title": _find_text(item, ["title"]),
                "link": link,
                "guid": guid,
                "published_at": (to_datetime(published_raw) or utc_now()).isoformat(),
                "summary": _find_text(item, ["description"]),
                "tags": list(source.tags or []),
                "raw_meta": {"published_raw": published_raw},
            }
        )
    return items


def parse_atom_items(xml_text: str, source: SourceConfig) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        link = ""
        for node in entry.findall("atom:link", ATOM_NS):
            href = str(node.attrib.get("href") or "").strip()
            rel = str(node.attrib.get("rel") or "").strip()
            if href and (not rel or rel == "alternate"):
                link = href
                break
        guid = _find_text(entry, ["atom:id"]) or link
        published_raw = _find_text(entry, ["atom:published", "atom:updated"])
        items.append(
            {
                "id": f"{source.source_type}:{guid or link or _find_text(entry, ['atom:title'])}",
                "source_name": source.name,
                "source_type": source.source_type,
                "feed_url": source.feed_url,
                "title": _find_text(entry, ["atom:title"]),
                "link": link,
                "guid": guid,
                "published_at": (to_datetime(published_raw) or utc_now()).isoformat(),
                "summary": _find_text(entry, ["atom:summary", "atom:content"]),
                "tags": list(source.tags or []),
                "raw_meta": {"published_raw": published_raw},
            }
        )
    return items


def parse_feed(xml_text: str, source: SourceConfig) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    tag = root.tag.lower()
    if tag.endswith("rss") or tag.endswith("rdf"):
        return parse_rss_items(xml_text, source)
    if tag.endswith("feed"):
        return parse_atom_items(xml_text, source)
    return []


def collect_source_items(source: SourceConfig, *, lookback_days: int, default_max_items: int) -> List[Dict[str, Any]]:
    xml_text = fetch_text(source.feed_url)
    items = parse_feed(xml_text, source)
    cutoff = utc_now() - timedelta(days=max(0, lookback_days))
    filtered: List[Dict[str, Any]] = []
    for item in items:
        published_at = to_datetime(str(item.get("published_at") or ""))
        if published_at is not None and published_at < cutoff:
            continue
        filtered.append(item)
    filtered.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    limit = source.max_items or default_max_items
    return filtered[: max(0, limit)]


def dedup_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = str(item.get("id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-collect")
    subparsers = parser.add_subparsers(dest="command")

    collect = subparsers.add_parser("collect")
    collect.add_argument("--config", required=True)
    collect.add_argument("--output", required=True)
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
    if args.command == "collect":
        sources = load_sources(Path(args.config))
        settings = load_rss_settings(Path(args.config))
        items: List[Dict[str, Any]] = []
        source_stats = []
        for source in sources:
            source_items = collect_source_items(
                source,
                lookback_days=int(settings["lookback_days"]),
                default_max_items=int(settings["max_items_per_source"]),
            )
            items.extend(source_items)
            source_stats.append(
                {
                    "name": source.name,
                    "type": source.source_type,
                    "feed_url": source.feed_url,
                    "item_count": len(source_items),
                }
            )
        items = dedup_items(items)
        payload = {
            "mode": "rss-raw",
            "generated_at": utc_now().isoformat(),
            "source_count": len(sources),
            "item_count": len(items),
            "sources": source_stats,
            "items": items,
        }
        save_json(Path(args.output), payload)
        print(
            json.dumps(
                {
                    "mode": "rss-raw",
                    "output": args.output,
                    "source_count": len(sources),
                    "item_count": len(items),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
