#!/usr/bin/env python3
"""Verify that a FollowHub daily run completed locally and on R2."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


SOURCE_TYPES = ("arxiv", "wechat", "x", "bilibili")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _integer_counts(value: Mapping[str, Any]) -> Dict[str, int]:
    return {source: int(value.get(source, 0) or 0) for source in SOURCE_TYPES}


def _section_counts(payload: Mapping[str, Any]) -> Dict[str, int]:
    counts = {source: 0 for source in SOURCE_TYPES}
    for section in payload.get("sections") or []:
        source = str(section.get("source_type") or "").strip().lower()
        if source not in counts:
            continue
        items = list(section.get("items") or [])
        declared = int(section.get("count", len(items)) or 0)
        if declared != len(items):
            raise ValueError(
                "section count mismatch for {0}: declared={1}, items={2}".format(
                    source, declared, len(items)
                )
            )
        counts[source] += len(items)
    return counts


def _item_date(item: Mapping[str, Any]) -> str:
    for key in ("date", "published", "published_at", "updated"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:10]
    return ""


def count_items_for_date(items: Iterable[Mapping[str, Any]], run_date: str) -> int:
    return sum(1 for item in items if _item_date(item) == run_date)


def _collection_error_kind(message: str) -> str:
    lowered = message.lower()
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "name or service not known" in lowered or "dns" in lowered:
        return "dns"
    return "other"


def summarize_collection_health(payload: Mapping[str, Any]) -> Dict[str, Any]:
    health: Dict[str, Any] = {}
    for source_type in ("wechat", "x", "bilibili", "rss"):
        rows = [
            row
            for row in payload.get("sources") or []
            if str(row.get("type") or row.get("source_type") or "").strip().lower()
            == source_type
        ]
        if not rows:
            continue
        errors = [str(row.get("error") or "") for row in rows if row.get("status") == "error"]
        error_kinds: Dict[str, int] = {}
        for message in errors:
            kind = _collection_error_kind(message)
            error_kinds[kind] = error_kinds.get(kind, 0) + 1
        health[source_type] = {
            "total": len(rows),
            "ok": sum(row.get("status") == "ok" for row in rows),
            "error": sum(row.get("status") == "error" for row in rows),
            "item_count": sum(int(row.get("item_count", 0) or 0) for row in rows),
            "error_kinds": error_kinds,
        }
    return health


def expected_local_counts(repo: Path, run_date: str) -> Dict[str, Any]:
    arxiv_verify_path = repo / "arxiv-daily-output" / run_date / "verify.json"
    rss_verify_path = repo / "rss-daily-output" / run_date / "verify.json"
    rss_digest_path = repo / "rss-daily-output" / run_date / "daily-digest.json"
    rss_collect_path = repo / "rss-collect-output" / "{0}-raw.json".format(run_date)

    missing = [
        str(path)
        for path in (
            arxiv_verify_path,
            rss_verify_path,
            rss_digest_path,
            rss_collect_path,
        )
        if not path.exists()
    ]
    if missing:
        return {
            "ok": False,
            "reason": "missing local verification artifacts",
            "missing": missing,
        }

    arxiv_verify = load_json(arxiv_verify_path)
    rss_verify = load_json(rss_verify_path)
    rss_digest = load_json(rss_digest_path)
    collection_health = summarize_collection_health(load_json(rss_collect_path))

    x_health = collection_health.get("x") or {}
    if int(x_health.get("total", 0) or 0) > 0 and int(x_health.get("ok", 0) or 0) == 0:
        return {
            "ok": False,
            "reason": "X/Twitter RSS collection is unavailable",
            "collection_health": collection_health,
        }

    arxiv_ok = bool(arxiv_verify.get("ok", True)) and not list(
        arxiv_verify.get("incomplete_summary_ids") or []
    )
    rss_ok = bool(rss_verify.get("ok", False))
    if not arxiv_ok or not rss_ok:
        return {
            "ok": False,
            "reason": "local verification did not pass",
            "arxiv_ok": arxiv_ok,
            "rss_ok": rss_ok,
        }

    counts = _integer_counts(rss_digest.get("counts") or {})
    counts["arxiv"] = int(arxiv_verify.get("daily_item_count", 0) or 0)
    rss_story_count = int(
        ((rss_verify.get("content_checks") or {}).get("story_count", 0)) or 0
    )
    expected_rss_count = sum(counts[source] for source in SOURCE_TYPES if source != "arxiv")
    if rss_story_count != expected_rss_count:
        return {
            "ok": False,
            "reason": "RSS digest and verification counts differ",
            "rss_story_count": rss_story_count,
            "rss_digest_count": expected_rss_count,
        }
    if sum(counts.values()) <= 0:
        return {"ok": False, "reason": "daily digest contains no selected items"}
    return {"ok": True, "counts": counts, "collection_health": collection_health}


def evaluate_remote_payloads(
    *,
    run_date: str,
    expected_counts: Mapping[str, int],
    daily: Mapping[str, Any],
    latest: Mapping[str, Any],
    source_payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    if str(daily.get("date") or "") != run_date:
        return {"ok": False, "reason": "remote daily date mismatch"}
    if str(latest.get("date") or "") != run_date:
        return {"ok": False, "reason": "remote latest date mismatch"}

    expected = _integer_counts(expected_counts)
    daily_counts = _integer_counts(daily.get("counts") or {})
    latest_counts = _integer_counts(latest.get("counts") or {})
    try:
        daily_section_counts = _section_counts(daily)
        latest_section_counts = _section_counts(latest)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}

    if daily_counts != expected or daily_section_counts != expected:
        return {
            "ok": False,
            "reason": "remote daily counts mismatch",
            "expected_counts": expected,
            "daily_counts": daily_counts,
            "daily_section_counts": daily_section_counts,
        }
    if latest_counts != expected or latest_section_counts != expected:
        return {
            "ok": False,
            "reason": "remote latest counts mismatch",
            "expected_counts": expected,
            "latest_counts": latest_counts,
            "latest_section_counts": latest_section_counts,
        }

    source_today_counts: Dict[str, int] = {}
    for source, expected_count in expected.items():
        if expected_count <= 0:
            continue
        payload = source_payloads.get(source)
        if payload is None:
            return {
                "ok": False,
                "reason": "missing remote source payload",
                "source": source,
            }
        today_count = count_items_for_date(payload.get("items") or [], run_date)
        source_today_counts[source] = today_count
        if today_count != expected_count:
            return {
                "ok": False,
                "reason": "remote source count mismatch",
                "source": source,
                "expected_count": expected_count,
                "today_count": today_count,
            }

    return {
        "ok": True,
        "reason": "local and remote daily artifacts match",
        "date": run_date,
        "counts": expected,
        "total_count": sum(expected.values()),
        "source_today_counts": source_today_counts,
    }


def _load_follow_publish_module(repo: Path) -> Any:
    path = repo / "skill" / "follow-publish" / "follow_publish.py"
    spec = importlib.util.spec_from_file_location("followhub_scheduled_follow_publish", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load follow-publish module: {0}".format(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fetch_remote_payloads(
    repo: Path, run_date: str, expected_counts: Mapping[str, int]
) -> Dict[str, Any]:
    module = _load_follow_publish_module(repo)
    rcli_module = module.load_rcli_module()
    daily = module.fetch_remote_json(rcli_module, "follow", "daily/{0}.json".format(run_date))
    latest = module.fetch_remote_json(rcli_module, "follow", "latest.json")
    if daily is None or latest is None:
        return {"daily": daily or {}, "latest": latest or {}, "sources": {}}

    sources: Dict[str, Dict[str, Any]] = {}
    for source, count in _integer_counts(expected_counts).items():
        if count <= 0:
            continue
        payload = module.fetch_remote_json(
            rcli_module, "follow", "sources/{0}.json".format(source)
        )
        if payload is not None:
            sources[source] = payload
    return {"daily": daily, "latest": latest, "sources": sources}


def check_daily_success(repo: Path, run_date: str, config_path: Path) -> Dict[str, Any]:
    local = expected_local_counts(repo, run_date)
    if not local.get("ok"):
        return local

    os.environ["FOLLOWHUB_CONFIG"] = str(config_path)
    try:
        remote = fetch_remote_payloads(repo, run_date, local["counts"])
        result = evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=local["counts"],
            daily=remote["daily"],
            latest=remote["latest"],
            source_payloads=remote["sources"],
        )
        result["collection_health"] = local.get("collection_health") or {}
        return result
    except Exception as exc:
        return {
            "ok": False,
            "reason": "remote verification failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check-followhub-daily-success")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--config")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    config_path = Path(args.config or repo / "followhub.yaml").expanduser().resolve()
    result = check_daily_success(repo, args.date, config_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
