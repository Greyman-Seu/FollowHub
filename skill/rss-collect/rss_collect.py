#!/usr/bin/env python3
"""Collect raw RSS entries into a shared raw bundle."""

from __future__ import annotations

import argparse
import concurrent.futures
import email.utils
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    import requests as _requests  # type: ignore
except Exception:
    _requests = None


HELP_TEXT = """\
rss-collect: Collect raw RSS entries.

Usage:
    rss-collect help
    rss-collect collect --config followhub.yaml --output rss-collect-output/2026-05-12-raw.json
    rss-collect prune-stale --source-file rss_sources_x_nitter.yaml --config followhub.yaml --apply
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
X_SOURCE_HOSTS = {"nitter.net"}


def resolve_proxy_settings(rss: Dict[str, Any]) -> Dict[str, str]:
    proxy = rss.get("proxy") or {}
    if not isinstance(proxy, dict):
        proxy = {}
    resolved: Dict[str, str] = {}
    key_map = {
        "http": "HTTP_PROXY",
        "https": "HTTPS_PROXY",
        "all_proxy": "ALL_PROXY",
        "no_proxy": "NO_PROXY",
    }
    for config_key, env_key in key_map.items():
        env_value = str(os.environ.get(env_key) or "").strip()
        if env_value:
            resolved[env_key] = env_value
            continue
        config_value = str(proxy.get(config_key) or "").strip()
        if config_value:
            resolved[env_key] = config_value
    return resolved


def apply_proxy_settings(proxy_settings: Dict[str, str]) -> None:
    for env_key, value in proxy_settings.items():
        if value:
            os.environ[env_key] = value


def format_network_error(exc: Exception, proxy_settings: Dict[str, str]) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    has_proxy = any(proxy_settings.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))

    if "nodename nor servname provided" in lowered or "name or service not known" in lowered:
        hint = (
            " DNS 解析失败。"
            + (
                " 当前未检测到代理，请先设置 HTTP_PROXY/HTTPS_PROXY（Clash 常见为 http://127.0.0.1:7890），"
                  "如果你不确定代理地址，先问用户。"
                if not has_proxy
                else " 当前已设置代理，但域名仍无法解析，请检查代理是否生效或代理地址是否正确。"
            )
        )
        return f"{message}.{hint}"

    if "connection refused" in lowered or "failed to connect" in lowered:
        return (
            f"{message}. 代理或目标服务拒绝连接。"
            " 请检查 HTTP_PROXY/HTTPS_PROXY 是否指向正确端口；如果不确定代理地址，先问用户。"
        )

    if "operation not permitted" in lowered:
        return (
            f"{message}. 当前 shell 进程无法直接连接网络或本地代理端口。"
            " 如果浏览器可访问但终端不行，先确认代理/VPN是否对当前 shell 生效；必要时重开 shell 或让用户确认代理接管范围。"
        )

    if "timed out" in lowered or "timeout" in lowered:
        return (
            f"{message}. 请求超时。"
            + (
            " 当前未检测到代理，Nitter/X 类源通常需要代理。请先设置 HTTP_PROXY/HTTPS_PROXY；如果不确定，先问用户。"
                if not has_proxy
                else " 请检查代理连通性，或缩小源列表做抽样验证。"
            )
        )

    return message


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


def load_source_file_document(path: Path) -> Tuple[Dict[str, Any], str]:
    raw_text = path.read_text(encoding="utf-8")
    lines = raw_text.splitlines(keepends=True)
    header_lines: List[str] = []
    body_start = 0
    for line in lines:
        if line.lstrip().startswith("#") or not line.strip():
            header_lines.append(line)
            body_start += len(line)
            continue
        break
    body_text = raw_text[body_start:]
    if yaml is None:
        raise SystemExit("PyYAML is required to load rss config files.")
    data = yaml.safe_load(body_text) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Source file must contain a top-level mapping: {path}")
    return data, "".join(header_lines)


def save_source_file_document(path: Path, data: Dict[str, Any], header_text: str = "") -> None:
    if yaml is None:
        raise SystemExit("PyYAML is required to save rss config files.")
    rendered = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(f"{header_text}{rendered}", encoding="utf-8")


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
    collect = rss.get("collect") if isinstance(rss, dict) else {}
    lookback_days = int((daily or {}).get("lookback_days") or 2) if isinstance(daily, dict) else 2
    max_items_per_source = int((daily or {}).get("max_items_per_source") or 50) if isinstance(daily, dict) else 50
    max_workers = int((collect or {}).get("max_workers") or 8) if isinstance(collect, dict) else 8
    request_timeout = int((collect or {}).get("request_timeout_seconds") or 30) if isinstance(collect, dict) else 30
    proxy_settings = resolve_proxy_settings(rss if isinstance(rss, dict) else {})
    return {
        "lookback_days": lookback_days,
        "max_items_per_source": max_items_per_source,
        "max_workers": max(1, max_workers),
        "request_timeout_seconds": max(1, request_timeout),
        "proxy_settings": proxy_settings,
    }


def source_hostname(source: SourceConfig) -> str:
    try:
        return str(urlparse(source.feed_url).hostname or "").strip().lower()
    except Exception:
        return ""


def is_x_style_source(source: SourceConfig) -> bool:
    return source.source_type == "x" or source_hostname(source) in X_SOURCE_HOSTS


def is_retryable_fetch_error(exc: Exception) -> bool:
    lowered = str(exc).strip().lower()
    retry_hints = (
        "timed out",
        "timeout",
        "temporary",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "ssl",
        "tls",
        "503",
        "502",
        "429",
    )
    return any(hint in lowered for hint in retry_hints)


def collect_policy(settings: Dict[str, Any], source: SourceConfig) -> Dict[str, Any]:
    workers = int(settings["max_workers"])
    timeout = int(settings["request_timeout_seconds"])
    if is_x_style_source(source):
        return {
            "max_workers": min(4, workers) if workers > 1 else 1,
            "request_timeout_seconds": min(12, max(8, timeout)),
            "retry_count": 1,
            "retry_backoff_seconds": 0.5,
        }
    return {
        "max_workers": workers,
        "request_timeout_seconds": timeout,
        "retry_count": 0,
        "retry_backoff_seconds": 0.0,
    }


def fetch_text(url: str, timeout: int = 30) -> str:
    hostname = str(urlparse(url).hostname or "").strip().lower()
    headers = {
        "User-Agent": "followhub-rss-collect/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    }

    if hostname in X_SOURCE_HOSTS and _requests is not None:
        response = _requests.get(url, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.text

    if hostname in X_SOURCE_HOSTS and shutil.which("curl"):
        proc = subprocess.run(
            [
                "curl",
                "-L",
                "--max-time",
                str(max(1, int(timeout))),
                "-A",
                headers["User-Agent"],
                "-H",
                f"Accept: {headers['Accept']}",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"curl exited with status {proc.returncode}")
    request = urllib.request.Request(
        url,
        headers=headers,
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


def collect_source_items(
    source: SourceConfig,
    *,
    lookback_days: int,
    default_max_items: int,
    request_timeout_seconds: int,
) -> List[Dict[str, Any]]:
    xml_text = fetch_text(source.feed_url, timeout=request_timeout_seconds)
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


def fetch_source_activity(
    source: SourceConfig,
    *,
    request_timeout_seconds: int,
    proxy_settings: Dict[str, str],
) -> Tuple[Optional[datetime], Dict[str, Any]]:
    try:
        xml_text = fetch_text(source.feed_url, timeout=request_timeout_seconds)
        items = parse_feed(xml_text, source)
    except Exception as exc:
        return None, {
            "name": source.name,
            "type": source.source_type,
            "feed_url": source.feed_url,
            "status": "error",
            "error": format_network_error(exc, proxy_settings),
            "total_items": 0,
        }

    if not items:
        return None, {
            "name": source.name,
            "type": source.source_type,
            "feed_url": source.feed_url,
            "status": "error",
            "error": "parsed 0 items from feed",
            "total_items": 0,
        }

    latest: Optional[datetime] = None
    for item in items:
        published = to_datetime(str(item.get("published_at") or "")) or utc_now()
        if latest is None or published > latest:
            latest = published

    return latest, {
        "name": source.name,
        "type": source.source_type,
        "feed_url": source.feed_url,
        "status": "ok",
        "total_items": len(items),
        "latest_published_at": latest.isoformat() if latest else "",
    }


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

    prune = subparsers.add_parser("prune-stale")
    prune.add_argument("--source-file", required=True)
    prune.add_argument("--config")
    prune.add_argument("--output-report")
    prune.add_argument("--stale-days", type=int, default=183)
    prune.add_argument("--request-timeout-seconds", type=int)
    prune.add_argument("--max-workers", type=int)
    prune.add_argument("--apply", action="store_true")
    return parser


def prune_stale_sources(
    *,
    source_file: Path,
    proxy_settings: Dict[str, str],
    stale_days: int,
    request_timeout_seconds: int,
    max_workers: int,
    apply_changes: bool,
) -> Dict[str, Any]:
    data, header_text = load_source_file_document(source_file)
    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raw_sources = []

    entries: List[Tuple[Dict[str, Any], SourceConfig]] = []
    preserved_invalid: List[Dict[str, Any]] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        parsed = _coerce_source(raw)
        if parsed is None:
            preserved_invalid.append(raw)
            continue
        entries.append((raw, parsed))

    cutoff = utc_now() - timedelta(days=max(0, stale_days))
    fresh_keys = set()
    stale_rows: List[Dict[str, Any]] = []
    broken_rows: List[Dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(
                fetch_source_activity,
                parsed,
                request_timeout_seconds=request_timeout_seconds,
                proxy_settings=dict(proxy_settings),
            ): (raw, parsed)
            for raw, parsed in entries
        }
        for future in concurrent.futures.as_completed(futures):
            raw, parsed = futures[future]
            latest, info = future.result()
            key = (parsed.source_type, parsed.name, parsed.feed_url)
            if latest is None:
                broken_rows.append(info)
                continue
            if latest < cutoff:
                stale_rows.append(
                    {
                        "name": parsed.name,
                        "type": parsed.source_type,
                        "feed_url": parsed.feed_url,
                        "latest_published_at": latest.isoformat(),
                        "total_items": int(info.get("total_items") or 0),
                    }
                )
                continue
            fresh_keys.add(key)

    stale_key_set = {(row["type"], row["name"], row["feed_url"]) for row in stale_rows}
    broken_key_set = {(row["type"], row["name"], row["feed_url"]) for row in broken_rows}

    kept_sources: List[Dict[str, Any]] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            kept_sources.append(raw)
            continue
        parsed = _coerce_source(raw)
        if parsed is None:
            kept_sources.append(raw)
            continue
        key = (parsed.source_type, parsed.name, parsed.feed_url)
        if key in stale_key_set or key in broken_key_set:
            continue
        kept_sources.append(raw)

    report = {
        "mode": "rss-source-prune",
        "generated_at": utc_now().isoformat(),
        "source_file": str(source_file),
        "stale_days": int(stale_days),
        "apply_changes": bool(apply_changes),
        "source_count_before": len(entries),
        "source_count_after": len(kept_sources),
        "stale_count": len(stale_rows),
        "broken_count": len(broken_rows),
        "stale_sources": sorted(stale_rows, key=lambda row: str(row.get("latest_published_at") or "")),
        "broken_sources": sorted(broken_rows, key=lambda row: str(row.get("name") or "")),
    }

    if apply_changes:
        data["sources"] = kept_sources
        save_source_file_document(source_file, data, header_text=header_text)

    return report


def collect_one_source(
    source: SourceConfig,
    *,
    lookback_days: int,
    default_max_items: int,
    request_timeout_seconds: int,
    proxy_settings: Dict[str, str],
    retry_count: int = 0,
    retry_backoff_seconds: float = 0.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    last_exc: Optional[Exception] = None
    for attempt in range(max(0, retry_count) + 1):
        try:
            source_items = collect_source_items(
                source,
                lookback_days=lookback_days,
                default_max_items=default_max_items,
                request_timeout_seconds=request_timeout_seconds,
            )
            return source_items, {
                "name": source.name,
                "type": source.source_type,
                "feed_url": source.feed_url,
                "item_count": len(source_items),
                "status": "ok",
                "attempts": attempt + 1,
            }
        except Exception as exc:
            last_exc = exc
            if attempt >= retry_count or not is_retryable_fetch_error(exc):
                break
            if retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * (attempt + 1))

    return [], {
        "name": source.name,
        "type": source.source_type,
        "feed_url": source.feed_url,
        "item_count": 0,
        "status": "error",
        "error": format_network_error(last_exc or RuntimeError("unknown error"), proxy_settings),
        "attempts": max(0, retry_count) + 1,
    }


def collect_source_batch(
    sources: List[SourceConfig],
    *,
    lookback_days: int,
    default_max_items: int,
    request_timeout_seconds: int,
    proxy_settings: Dict[str, str],
    max_workers: int,
    retry_count: int,
    retry_backoff_seconds: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    stats: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(
                collect_one_source,
                source,
                lookback_days=lookback_days,
                default_max_items=default_max_items,
                request_timeout_seconds=request_timeout_seconds,
                proxy_settings=dict(proxy_settings),
                retry_count=retry_count,
                retry_backoff_seconds=retry_backoff_seconds,
            ): source
            for source in sources
        }
        for future in concurrent.futures.as_completed(futures):
            source_items, source_stat = future.result()
            items.extend(source_items)
            stats.append(source_stat)
    return items, stats


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
        apply_proxy_settings(dict(settings["proxy_settings"]))
        items: List[Dict[str, Any]] = []
        source_stats = []
        x_sources = [source for source in sources if is_x_style_source(source)]
        default_sources = [source for source in sources if not is_x_style_source(source)]

        if default_sources:
            default_items, default_stats = collect_source_batch(
                default_sources,
                lookback_days=int(settings["lookback_days"]),
                default_max_items=int(settings["max_items_per_source"]),
                request_timeout_seconds=int(settings["request_timeout_seconds"]),
                proxy_settings=dict(settings["proxy_settings"]),
                max_workers=int(settings["max_workers"]),
                retry_count=0,
                retry_backoff_seconds=0.0,
            )
            items.extend(default_items)
            source_stats.extend(default_stats)

        if x_sources:
            x_policy = collect_policy(settings, x_sources[0])
            x_items, x_stats = collect_source_batch(
                x_sources,
                lookback_days=int(settings["lookback_days"]),
                default_max_items=int(settings["max_items_per_source"]),
                request_timeout_seconds=int(x_policy["request_timeout_seconds"]),
                proxy_settings=dict(settings["proxy_settings"]),
                max_workers=int(x_policy["max_workers"]),
                retry_count=int(x_policy["retry_count"]),
                retry_backoff_seconds=float(x_policy["retry_backoff_seconds"]),
            )
            items.extend(x_items)
            source_stats.extend(x_stats)
        source_stats.sort(key=lambda item: str(item.get("name") or ""))
        items = dedup_items(items)
        payload = {
            "mode": "rss-raw",
            "generated_at": utc_now().isoformat(),
            "source_count": len(sources),
            "item_count": len(items),
            "max_workers": int(settings["max_workers"]),
            "x_source_count": len(x_sources),
            "proxy_enabled": bool(settings["proxy_settings"]),
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
    if args.command == "prune-stale":
        proxy_settings: Dict[str, str] = {}
        request_timeout_seconds = 20
        max_workers = 8
        if args.config:
            settings = load_rss_settings(Path(args.config))
            proxy_settings = dict(settings["proxy_settings"])
            request_timeout_seconds = int(settings["request_timeout_seconds"])
            max_workers = int(settings["max_workers"])
        if args.request_timeout_seconds is not None:
            request_timeout_seconds = max(1, int(args.request_timeout_seconds))
        if args.max_workers is not None:
            max_workers = max(1, int(args.max_workers))

        apply_proxy_settings(dict(proxy_settings))
        report = prune_stale_sources(
            source_file=Path(args.source_file),
            proxy_settings=proxy_settings,
            stale_days=max(0, int(args.stale_days)),
            request_timeout_seconds=request_timeout_seconds,
            max_workers=max_workers,
            apply_changes=bool(args.apply),
        )
        if args.output_report:
            save_json(Path(args.output_report), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
