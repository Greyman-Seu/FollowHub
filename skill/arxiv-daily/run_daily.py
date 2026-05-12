#!/usr/bin/env python3
"""Strict orchestrator for the arxiv-daily skill.

This script enforces the required stage order:
collect -> title-prefilter -> filter -> enrich -> publish -> verify

Subagents are an optional optimization. The contract is stage order and
required artifacts, not a specific concurrency model.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, NoReturn, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "arxiv-daily-output"
SUMMARY_OVERRIDES_PATH = Path(__file__).resolve().parent / "summary_overrides.json"
SOURCE_ORDER = ["arxiv", "wechat", "x", "bilibili"]


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def load_yaml(path: Path) -> Dict[str, object]:
    if yaml is None:
        fail("PyYAML is required to load arxiv-daily config files.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        fail(f"Config file must contain a top-level mapping: {path}")
    return data


def resolve_config_path(explicit: Optional[str]) -> Path:
    candidates = [
        explicit,
        os.environ.get("FOLLOWHUB_CONFIG"),
        str(REPO_ROOT / "followhub.yaml"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    fail("Could not resolve FollowHub config. Pass --config or set FOLLOWHUB_CONFIG.")


def run_command(args: List[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        fail(f"Command failed: {' '.join(args)}\n{detail}")
    return proc


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def today_string() -> str:
    return date.today().isoformat()


def normalize_text(value: object) -> str:
    return str(value or "").strip().lower()


def dedup_strings(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


@dataclass
class DailyPaths:
    run_root: Path
    raw_json: Path
    prefilter_results: Path
    filter_input: Path
    filter_results: Path
    enrich_input: Path
    enrich_results: Path
    digest_json: Path
    publish_dir: Path
    verify_json: Path


def build_paths(run_root: Path, run_date: str) -> DailyPaths:
    return DailyPaths(
        run_root=run_root,
        raw_json=run_root / "collect" / f"{run_date}-daily.json",
        prefilter_results=run_root / "prefilter_results.json",
        filter_input=run_root / "filter_input.json",
        filter_results=run_root / "filter_results.json",
        enrich_input=run_root / "enrich_input.json",
        enrich_results=run_root / "enrich_results.json",
        digest_json=run_root / "daily-digest.json",
        publish_dir=run_root / "publish-out",
        verify_json=run_root / "verify.json",
    )


def load_summary_overrides() -> Dict[str, Dict[str, str]]:
    if not SUMMARY_OVERRIDES_PATH.exists():
        return {}
    payload = load_json(SUMMARY_OVERRIDES_PATH)
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        return {}
    return {str(key): dict(value) for key, value in overrides.items() if isinstance(value, dict)}


def save_summary_overrides(overrides: Dict[str, Dict[str, str]]) -> None:
    write_json(SUMMARY_OVERRIDES_PATH, {"overrides": overrides})


def resolve_domain_config(config: Dict[str, object]) -> Dict[str, Dict[str, str]]:
    follow = config.get("follow") or {}
    domains = follow.get("domains") if isinstance(follow, dict) else {}
    result: Dict[str, Dict[str, str]] = {}
    if isinstance(domains, dict):
        for slug, item in domains.items():
            if isinstance(item, dict):
                result[str(slug)] = {"slug": str(slug), "name": str(item.get("name") or slug)}
    return result


def collect_daily(config_path: Path, output_root: Path) -> Dict[str, object]:
    collect_dir = output_root / "collect"
    collect_dir.mkdir(parents=True, exist_ok=True)
    proc = run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "arxiv-collect" / "arxiv_collect.py"),
            "run",
            "--mode",
            "daily",
            "--profile",
            str(config_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = json.loads(proc.stdout)
    written = payload.get("written") or {}
    raw_path = written.get("json")
    if not raw_path:
        fail("arxiv-collect did not report a written JSON file.")
    raw_source = REPO_ROOT / str(raw_path)
    if not raw_source.exists():
        fail(f"arxiv-collect JSON output not found: {raw_source}")
    raw_result = load_json(raw_source)
    run_date = str(raw_result.get("date") or "")
    if not run_date:
        fail("arxiv-collect output is missing 'date'.")
    run_root = output_root / run_date
    paths = build_paths(run_root, run_date)
    paths.raw_json.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_json.write_text(raw_source.read_text(encoding="utf-8"), encoding="utf-8")
    return raw_result


def ensure_listing_date(raw_payload: Dict[str, object], requested_date: str, allow_stale: bool) -> None:
    listing_date = str(raw_payload.get("listing_date") or "")
    if requested_date == today_string() and listing_date and listing_date != requested_date and not allow_stale:
        fail(
            f"arXiv listing_date is {listing_date}, not {requested_date}. "
            "Stopping before publish. Pass --allow-stale-listing to override."
        )


def keyword_lists(config: Dict[str, object]) -> Dict[str, List[str]]:
    arxiv = config.get("arxiv") or {}
    if not isinstance(arxiv, dict):
        return {"keywords": [], "exclude_keywords": []}
    return {
        "keywords": [normalize_text(item) for item in (arxiv.get("keywords") or []) if normalize_text(item)],
        "exclude_keywords": [normalize_text(item) for item in (arxiv.get("exclude_keywords") or []) if normalize_text(item)],
    }


def title_prefilter_decision(entry: Dict[str, object], config: Dict[str, object]) -> Dict[str, str]:
    title = normalize_text(entry.get("title"))
    categories = [normalize_text(item) for item in (entry.get("categories") or [])]
    keywords = keyword_lists(config)["keywords"]
    excludes = keyword_lists(config)["exclude_keywords"]
    if any(word in title for word in excludes):
        return {"decision": "drop", "reason": "title hit configured exclude keyword"}
    strong_hits = [word for word in keywords if word in title]
    if strong_hits:
        return {"decision": "keep", "reason": f"title hit focus keyword(s): {', '.join(strong_hits[:3])}"}
    if "cs.ro" in categories:
        return {"decision": "uncertain", "reason": "robotics category requires abstract-level review"}
    if "world model" in title or "policy" in title or "visuomotor" in title or "manipulation" in title:
        return {"decision": "uncertain", "reason": "title is adjacent to focus and should advance"}
    return {"decision": "drop", "reason": "title/category do not indicate the configured focus"}


def run_title_prefilter(raw_payload: Dict[str, object], config: Dict[str, object], output_path: Path) -> Dict[str, object]:
    entries = list(raw_payload.get("entries") or [])
    items = []
    for entry in entries:
        decision = title_prefilter_decision(entry, config)
        items.append(
            {
                "arxiv_id": str(entry.get("id") or ""),
                "decision": decision["decision"],
                "reason": decision["reason"],
            }
        )
    payload = {
        "mode": "title-prefilter",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "raw_count": len(entries),
        "items": items,
    }
    write_json(output_path, payload)
    return payload


def validate_prefilter_results(path: Path, raw_payload: Dict[str, object]) -> Dict[str, object]:
    payload = load_json(path)
    items = payload.get("items")
    if not isinstance(items, list):
        fail("prefilter_results.json must contain an 'items' list.")
    raw_ids = {str(entry.get("id") or "") for entry in (raw_payload.get("entries") or [])}
    seen = set()
    for item in items:
        arxiv_id = str(item.get("arxiv_id") or "")
        decision = str(item.get("decision") or "")
        if arxiv_id not in raw_ids:
            fail(f"prefilter_results.json contains unknown arxiv_id: {arxiv_id}")
        if decision not in {"keep", "drop", "uncertain", "direct-pass"}:
            fail(f"Invalid prefilter decision for {arxiv_id}: {decision}")
        seen.add(arxiv_id)
    missing = sorted(raw_ids - seen)
    if missing:
        fail(f"prefilter_results.json is missing decisions for {len(missing)} raw papers.")
    return payload


def build_filter_candidates(raw_payload: Dict[str, object], prefilter_payload: Dict[str, object]) -> List[Dict[str, object]]:
    entries_by_id = {str(entry.get("id") or ""): dict(entry) for entry in (raw_payload.get("entries") or [])}
    decisions = {
        str(item.get("arxiv_id") or ""): str(item.get("decision") or "")
        for item in (prefilter_payload.get("items") or [])
    }
    selected = []
    for arxiv_id, entry in entries_by_id.items():
        if decisions.get(arxiv_id) in {"keep", "uncertain", "direct-pass"}:
            selected.append(entry)
    if not selected:
        fail("No papers advanced to arxiv-filter. Stopping before publish.")
    return selected


def domain_for_entry(entry: Dict[str, object], domain_config: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    text = normalize_text(entry.get("title")) + "\n" + normalize_text(entry.get("abstract_en") or entry.get("summary"))
    slugs = []
    if any(word in text for word in ["robot", "manipulation", "visuomotor", "policy", "embodied", "world action model", "vla"]):
        slugs.append("physical-embodied-intelligence")
    if any(word in text for word in ["llm", "vlm", "vision-language-action", "vla", "multimodal"]):
        slugs.append("llm-vlm")
    if any(word in text for word in ["agent", "workflow", "planning", "verification"]):
        slugs.append("agent")
    if not slugs:
        slugs.append("physical-embodied-intelligence")
    result = []
    for slug in dedup_strings(slugs)[:2]:
        if slug in domain_config:
            result.append(domain_config[slug])
    return result


def filter_decision(entry: Dict[str, object], config: Dict[str, object], domain_config: Dict[str, Dict[str, str]], overrides: Dict[str, Dict[str, str]]) -> Dict[str, object]:
    arxiv_id = str(entry.get("id") or "")
    title = normalize_text(entry.get("title"))
    abstract = normalize_text(entry.get("abstract_en") or entry.get("summary"))
    combined = title + "\n" + abstract
    lists = keyword_lists(config)
    hit_count = sum(1 for word in lists["keywords"] if word and word in combined)
    has_exclude = any(word in combined for word in lists["exclude_keywords"])
    is_robotics = "cs.ro" in [normalize_text(item) for item in (entry.get("categories") or [])]
    include = False
    reason = ""
    if has_exclude:
        include = False
        reason = "hit configured exclude keyword in title or abstract"
    elif "vision-language-action" in combined or " vla" in combined or title.startswith("vla"):
        include = True
        reason = "direct VLA hit"
    elif "world model" in combined or "world action model" in combined:
        include = True
        reason = "world model is in focus"
    elif "manipulation" in combined and is_robotics:
        include = True
        reason = "robot manipulation is in focus"
    elif hit_count >= 2 and is_robotics:
        include = True
        reason = "multiple focus keyword hits in a robotics paper"
    elif hit_count >= 3:
        include = True
        reason = "multiple focus keyword hits"
    else:
        include = False
        reason = "outside the main VLA / manipulation / world-model line"
    override = overrides.get(arxiv_id, {})
    return {
        "arxiv_id": arxiv_id,
        "include_in_follow": include,
        "domains": domain_for_entry(entry, domain_config) if include else [],
        "one_liner_zh": str(override.get("one_liner_zh") or ""),
        "summary_cn": str(override.get("summary_cn") or ""),
        "reason": reason,
    }


def run_filter(
    raw_payload: Dict[str, object],
    filter_candidates: List[Dict[str, object]],
    config: Dict[str, object],
    domain_config: Dict[str, Dict[str, str]],
    output_path: Path,
) -> Dict[str, object]:
    overrides = load_summary_overrides()
    items = [filter_decision(entry, config, domain_config, overrides) for entry in filter_candidates]
    payload = {
        "mode": "filter",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "items": items,
    }
    write_json(output_path, payload)
    return payload


def repair_missing_summary_fields(
    *,
    filter_payload: Dict[str, object],
    enrich_payload: Dict[str, object],
) -> Dict[str, object]:
    overrides = load_summary_overrides()
    changed = False
    enrich_by_id = {str(entry.get("id") or ""): entry for entry in (enrich_payload.get("entries") or [])}
    for item in filter_payload.get("items", []):
        if not bool(item.get("include_in_follow", False)):
            continue
        arxiv_id = str(item.get("arxiv_id") or "")
        current_one_liner = str(item.get("one_liner_zh") or "").strip()
        current_summary = str(item.get("summary_cn") or "").strip()
        override = overrides.get(arxiv_id, {})
        if current_one_liner and current_summary:
            continue
        if override.get("one_liner_zh") and not current_one_liner:
            item["one_liner_zh"] = str(override["one_liner_zh"]).strip()
            changed = True
        if override.get("summary_cn") and not current_summary:
            item["summary_cn"] = str(override["summary_cn"]).strip()
            changed = True
        if not str(item.get("one_liner_zh") or "").strip():
            enriched = enrich_by_id.get(arxiv_id, {})
            inferred_one_liner = str(enriched.get("one_liner_zh") or "").strip()
            if inferred_one_liner:
                item["one_liner_zh"] = inferred_one_liner
                changed = True
        if not str(item.get("summary_cn") or "").strip():
            enriched = enrich_by_id.get(arxiv_id, {})
            inferred_summary = str(enriched.get("summary_cn") or "").strip()
            if inferred_summary:
                item["summary_cn"] = inferred_summary
                changed = True
    if changed:
        save_summary_overrides(overrides)
    return filter_payload


def ensure_required_summary_fields(filter_payload: Dict[str, object]) -> None:
    missing = []
    for item in filter_payload.get("items", []):
        if not bool(item.get("include_in_follow", False)):
            continue
        arxiv_id = str(item.get("arxiv_id") or "")
        if not str(item.get("one_liner_zh") or "").strip() or not str(item.get("summary_cn") or "").strip():
            missing.append(arxiv_id)
    if missing:
        fail(
            "Selected follow papers are still missing required Chinese summary fields after repair: "
            + ", ".join(missing)
        )


def validate_filter_results(path: Path, allowed_ids: List[str]) -> Dict[str, object]:
    payload = load_json(path)
    items = payload.get("items")
    if not isinstance(items, list):
        fail("filter_results.json must contain an 'items' list.")
    allowed = set(allowed_ids)
    seen = set()
    for item in items:
        arxiv_id = str(item.get("arxiv_id") or "")
        if arxiv_id not in allowed:
            fail(f"filter_results.json contains arxiv_id outside filter candidate set: {arxiv_id}")
        seen.add(arxiv_id)
    missing = sorted(allowed - seen)
    if missing:
        fail(f"filter_results.json is missing decisions for {len(missing)} candidate papers.")
    return payload


def build_enrich_input(raw_payload: Dict[str, object], filter_payload: Dict[str, object], output_path: Path) -> Dict[str, object]:
    entries_by_id = {str(entry.get("id") or ""): dict(entry) for entry in (raw_payload.get("entries") or [])}
    selected_ids = []
    rows = []
    for item in filter_payload.get("items", []):
        if bool(item.get("include_in_follow", False)):
            arxiv_id = str(item.get("arxiv_id") or "")
            entry = entries_by_id.get(arxiv_id)
            if entry is None:
                fail(f"Filter selected unknown arxiv_id for enrich: {arxiv_id}")
            selected_ids.append(arxiv_id)
            rows.append(entry)
    payload = {
        "mode": "daily",
        "date": str(raw_payload.get("date") or ""),
        "count": len(rows),
        "entries": rows,
        "selected_ids": selected_ids,
    }
    write_json(output_path, payload)
    return payload


def run_enrich(config_path: Path, enrich_input_path: Path, output_path: Path) -> Dict[str, object]:
    proc = run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "arxiv-enrich" / "arxiv_enrich.py"),
            "enrich",
            "--input",
            str(enrich_input_path),
            "--profile",
            str(config_path),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
    )
    if proc.stdout:
        try:
            json.loads(proc.stdout)
        except Exception:
            pass
    return load_json(output_path)


def validate_enrich_results(path: Path, selected_ids: List[str]) -> Dict[str, object]:
    payload = load_json(path)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        fail("enrich_results.json must contain an 'entries' list.")
    seen = {str(entry.get("id") or "") for entry in entries}
    missing = sorted(set(selected_ids) - seen)
    if missing:
        fail(f"enrich_results.json is missing {len(missing)} selected papers.")
    return payload


def importance_from_scores(entry: Dict[str, object]) -> str:
    score = float(entry.get("overall_score", 0) or 0)
    if score >= 2.45:
        return "high"
    if score >= 2.3:
        return "medium"
    return "low"


def build_digest(
    raw_payload: Dict[str, object],
    filter_payload: Dict[str, object],
    enrich_payload: Dict[str, object],
    domain_config: Dict[str, Dict[str, str]],
    output_path: Path,
) -> Dict[str, object]:
    filter_by_id = {str(item.get("arxiv_id") or ""): dict(item) for item in (filter_payload.get("items") or [])}
    enrich_by_id = {str(item.get("id") or ""): dict(item) for item in (enrich_payload.get("entries") or [])}
    items = []
    overrides = load_summary_overrides()
    for arxiv_id, filter_item in filter_by_id.items():
        if not bool(filter_item.get("include_in_follow", False)):
            continue
        enriched = enrich_by_id.get(arxiv_id)
        if not enriched:
            continue
        override = overrides.get(arxiv_id, {})
        one_liner = str(filter_item.get("one_liner_zh") or override.get("one_liner_zh") or enriched.get("one_liner_zh") or "")
        summary_cn = str(filter_item.get("summary_cn") or override.get("summary_cn") or enriched.get("summary_cn") or "")
        domains = filter_item.get("domains") or domain_for_entry(enriched, domain_config)
        items.append(
            {
                "id": f"arxiv:{arxiv_id}",
                "source_type": "arxiv",
                "title": str(enriched.get("title") or arxiv_id),
                "summary": one_liner or str(enriched.get("title") or arxiv_id),
                "importance": importance_from_scores(enriched),
                "include_in_follow": True,
                "authors": list(enriched.get("authors") or []),
                "categories": list(enriched.get("categories") or []),
                "author_meta": list(enriched.get("author_meta") or []),
                "first_affiliation": str(enriched.get("first_affiliation") or ""),
                "hjfy_url": str(enriched.get("hjfy_url") or ""),
                "published": str(enriched.get("published") or ""),
                "updated": str(enriched.get("updated") or ""),
                "abstract_en": str(enriched.get("abstract_en") or ""),
                "one_liner_zh": one_liner,
                "summary_cn": summary_cn,
                "hot_score": float(enriched.get("hot_score", 0) or 0),
                "overall_score": float(enriched.get("overall_score", 0) or 0),
                "relevance_score": float(enriched.get("relevance_score", 0) or 0),
                "is_favorite": bool(enriched.get("is_favorite", False)),
                "domains": list(domains),
                "links": dedup_links(
                    [
                        {"label": "Abs", "href": str(enriched.get("html_url") or "")},
                        {"label": "PDF", "href": str(enriched.get("pdf_url") or "")},
                    ]
                    + [{"label": f"Code {idx + 1}", "href": url} for idx, url in enumerate(enriched.get("code_urls") or [])]
                    + [{"label": f"Project {idx + 1}", "href": url} for idx, url in enumerate(enriched.get("project_urls") or [])]
                ),
            }
        )
    items.sort(key=lambda item: (item["importance"] == "high", item["overall_score"], item["title"]), reverse=True)
    highlights = [f"{item['title']}: {item['summary']}" for item in items[:3]]
    payload = {
        "date": str(raw_payload.get("date") or ""),
        "summary": f"{raw_payload.get('date')} arXiv daily selected {len(items)} papers for follow-up.",
        "highlights": highlights,
        "counts": {"arxiv": len(items), "wechat": 0, "x": 0, "bilibili": 0},
        "sections": [
            {
                "source_type": "arxiv",
                "title": "arXiv",
                "count": len(items),
                "items": items,
            }
        ],
    }
    write_json(output_path, payload)
    return payload


def dedup_links(links: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    result = []
    for link in links:
        href = str(link.get("href") or "").strip()
        label = str(link.get("label") or "").strip()
        if not href or (label, href) in seen:
            continue
        seen.add((label, href))
        result.append({"label": label, "href": href})
    return result


def verify_publish_inputs(paths: DailyPaths) -> None:
    required = [
        paths.raw_json,
        paths.prefilter_results,
        paths.filter_input,
        paths.filter_results,
        paths.enrich_input,
        paths.enrich_results,
        paths.digest_json,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        fail("Refusing to publish because required artifacts are missing:\n" + "\n".join(missing))


def build_verify_file(paths: DailyPaths, digest_payload: Dict[str, object]) -> None:
    sections = list(digest_payload.get("sections") or [])
    first_count = len(sections[0].get("items") or []) if sections else 0
    write_json(
        paths.verify_json,
        {
            "date": digest_payload.get("date") or "",
            "counts": digest_payload.get("counts") or {},
            "daily_item_count": first_count,
            "required_checks": [
                "follow/latest.json",
                f"follow/daily/{digest_payload.get('date')}.json",
                "follow/sources/arxiv.json",
            ],
        },
    )


def command_daily(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    config = load_yaml(config_path)
    output_root = Path(args.output_root or DEFAULT_OUTPUT_ROOT)
    output_root.mkdir(parents=True, exist_ok=True)

    raw_payload = collect_daily(config_path, output_root)
    run_date = str(raw_payload.get("date") or "")
    paths = build_paths(output_root / run_date, run_date)
    ensure_listing_date(raw_payload, args.date or today_string(), args.allow_stale_listing)

    prefilter_payload = run_title_prefilter(raw_payload, config, paths.prefilter_results)
    prefilter_payload = validate_prefilter_results(paths.prefilter_results, raw_payload)

    filter_candidates = build_filter_candidates(raw_payload, prefilter_payload)
    write_json(paths.filter_input, {"mode": "filter", "count": len(filter_candidates), "entries": filter_candidates})
    domain_config = resolve_domain_config(config)
    filter_payload = run_filter(raw_payload, filter_candidates, config, domain_config, paths.filter_results)
    filter_payload = validate_filter_results(paths.filter_results, [str(entry.get("id") or "") for entry in filter_candidates])

    enrich_input_payload = build_enrich_input(raw_payload, filter_payload, paths.enrich_input)
    selected_ids = list(enrich_input_payload.get("selected_ids") or [])
    if selected_ids:
        enrich_payload = run_enrich(config_path, paths.enrich_input, paths.enrich_results)
        enrich_payload = validate_enrich_results(paths.enrich_results, selected_ids)
    else:
        enrich_payload = {"mode": "daily", "entries": []}
        write_json(paths.enrich_results, enrich_payload)

    filter_payload = repair_missing_summary_fields(filter_payload=filter_payload, enrich_payload=enrich_payload)
    write_json(paths.filter_results, filter_payload)
    ensure_required_summary_fields(filter_payload)

    digest_payload = build_digest(raw_payload, filter_payload, enrich_payload, domain_config, paths.digest_json)
    verify_publish_inputs(paths)

    command = "publish-daily" if args.publish else "build-daily"
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "follow-publish" / "follow_publish.py"),
            command,
            "--input",
            str(paths.digest_json),
            "--output-dir",
            str(paths.publish_dir),
            "--config",
            str(config_path),
        ],
        cwd=REPO_ROOT,
    )

    build_verify_file(paths, digest_payload)
    print(
        json.dumps(
            {
                "date": run_date,
                "run_root": str(paths.run_root),
                "raw_json": str(paths.raw_json),
                "prefilter_results": str(paths.prefilter_results),
                "filter_input": str(paths.filter_input),
                "filter_results": str(paths.filter_results),
                "enrich_input": str(paths.enrich_input),
                "enrich_results": str(paths.enrich_results),
                "digest_json": str(paths.digest_json),
                "publish_dir": str(paths.publish_dir),
                "verify_json": str(paths.verify_json),
                "published": bool(args.publish),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_backfill(args: argparse.Namespace) -> int:
    fail("Backfill orchestration is not implemented yet.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-daily")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily = subparsers.add_parser("daily")
    daily.add_argument("--config")
    daily.add_argument("--date", default=today_string())
    daily.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    daily.add_argument("--allow-stale-listing", action="store_true")
    daily.add_argument("--publish", action="store_true")
    daily.set_defaults(func=command_daily)

    backfill = subparsers.add_parser("backfill")
    backfill.add_argument("--config")
    backfill.add_argument("--from-date", required=True)
    backfill.add_argument("--to-date", required=True)
    backfill.set_defaults(func=command_backfill)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
