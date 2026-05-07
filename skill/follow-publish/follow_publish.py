#!/usr/bin/env python3
"""
follow_publish.py - Build Follow page data artifacts from follow digests or arXiv results.
"""

import argparse
import importlib.util
import json
import subprocess
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None


HELP_TEXT = """\
follow-publish: Build Follow page data artifacts.

Usage:
    follow-publish help
    follow-publish build-daily --input /path/to/follow-daily.json --output-dir ./follow-publish-out
    follow-publish build-from-arxiv --input /path/to/arxiv-find-output.json --output-dir ./follow-publish-out
    follow-publish publish-daily --input /path/to/follow-daily.json --remote-prefix follow
    follow-publish rebuild-index --daily-dir ./follow-history --output-dir ./follow-publish-out
"""

SOURCE_ORDER = ("arxiv", "wechat", "x", "bilibili")
RECENT_SOURCE_DAYS = 30
IMPORTANCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}
UNCATEGORIZED_DOMAIN = {"slug": "uncategorized", "name": "Uncategorized"}
DEFAULT_DOMAIN_CONFIG = {
    "domains": {
        "llm-vlm": {
            "name": "LLM/VLM",
            "keywords": ["llm", "vlm", "multimodal", "vision-language", "reasoning"],
            "categories": ["cs.AI", "cs.CL", "cs.LG", "cs.CV", "cs.MM"],
        },
        "physical-embodied-intelligence": {
            "name": "Physical/Embodied Intelligence",
            "keywords": ["robot", "robotics", "manipulation", "embodied", "vla", "policy"],
            "categories": ["cs.RO"],
        },
        "aigc": {
            "name": "AIGC",
            "keywords": ["diffusion", "image generation", "video generation", "image editing", "video editing"],
            "categories": ["cs.CV", "cs.MM"],
        },
        "agent": {
            "name": "Agent",
            "keywords": ["agent", "tool use", "planning", "workflow", "browser", "code agent"],
            "categories": ["cs.AI"],
        },
    }
}


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def normalize_source_name(source: str) -> str:
    mapping = {
        "arxiv": "arXiv",
        "wechat": "WeChat",
        "x": "X / Twitter",
        "bilibili": "Bilibili",
    }
    return mapping.get(source, source)


def normalize_importance(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in IMPORTANCE_WEIGHT else "medium"


def validate_digest(digest: Dict[str, Any]) -> Dict[str, Any]:
    if not digest.get("date"):
        raise ValueError("Follow digest must contain 'date'")
    if not isinstance(digest.get("sections"), list):
        raise ValueError("Follow digest must contain 'sections' list")

    normalized = {
        "date": str(digest["date"]),
        "summary": str(digest.get("summary") or "").strip(),
        "highlights": [str(item).strip() for item in (digest.get("highlights") or []) if str(item).strip()],
        "counts": {source: int((digest.get("counts") or {}).get(source) or 0) for source in SOURCE_ORDER},
        "sections": [],
    }

    for section in digest.get("sections", []):
        source_type = str(section.get("source_type") or section.get("sourceType") or "").strip()
        if source_type not in SOURCE_ORDER:
            raise ValueError(f"Unsupported source_type in digest section: {source_type!r}")
        items = []
        for item in section.get("items", []):
            items.append(
                {
                    "id": str(item.get("id") or "").strip(),
                    "source_type": source_type,
                    "title": str(item.get("title") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "importance": normalize_importance(item.get("importance")),
                    "include_in_follow": bool(item.get("include_in_follow", True)),
                    "authors": [str(author).strip() for author in (item.get("authors") or []) if str(author).strip()],
                    "categories": [str(category).strip() for category in (item.get("categories") or []) if str(category).strip()],
                    "author_meta": [
                        {
                            "name": str(author.get("name") or "").strip(),
                            "affiliations": [str(aff).strip() for aff in (author.get("affiliations") or []) if str(aff).strip()],
                            "is_first_author": bool(author.get("is_first_author", False)),
                            "is_corresponding_author": bool(author.get("is_corresponding_author", False)),
                        }
                        for author in (item.get("author_meta") or [])
                        if str(author.get("name") or "").strip()
                    ],
                    "first_affiliation": str(item.get("first_affiliation") or "").strip(),
                    "hjfy_url": str(item.get("hjfy_url") or "").strip(),
                    "published": str(item.get("published") or "").strip(),
                    "updated": str(item.get("updated") or "").strip(),
                    "abstract_en": str(item.get("abstract_en") or "").strip(),
                    "one_liner_zh": str(item.get("one_liner_zh") or "").strip(),
                    "summary_cn": str(item.get("summary_cn") or "").strip(),
                    "hot_score": float(item.get("hot_score", 0) or 0),
                    "overall_score": float(item.get("overall_score", 0) or 0),
                    "relevance_score": float(item.get("relevance_score", 0) or 0),
                    "is_favorite": bool(item.get("is_favorite", False)),
                    "domains": [
                        {
                            "slug": str(domain.get("slug") or domain).strip(),
                            "name": str(domain.get("name") or domain).strip(),
                        }
                        for domain in (item.get("domains") or [])
                        if str((domain.get("slug") if isinstance(domain, dict) else domain) or "").strip()
                    ],
                    "links": [
                        {"label": str(link.get("label") or "").strip(), "href": str(link.get("href") or "").strip()}
                        for link in (item.get("links") or [])
                        if str(link.get("href") or "").strip()
                    ],
                }
            )
        normalized["sections"].append(
            {
                "source_type": source_type,
                "title": str(section.get("title") or normalize_source_name(source_type)).strip(),
                "count": len(items),
                "items": items,
            }
        )

    normalized["counts"] = {
        source: sum(section["count"] for section in normalized["sections"] if section["source_type"] == source)
        for source in SOURCE_ORDER
    }
    return normalized


def load_digests(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    digests = [validate_digest(load_json(path)) for path in paths]
    digests.sort(key=lambda item: item["date"], reverse=True)
    return digests


def load_digests_from_directory(directory: Path) -> List[Dict[str, Any]]:
    files = sorted(directory.glob("*.json"), reverse=True)
    return load_digests(files)


def load_domain_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return deepcopy(DEFAULT_DOMAIN_CONFIG)
    if yaml is None:
        raise RuntimeError("PyYAML is required to load follow domain config.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return deepcopy(DEFAULT_DOMAIN_CONFIG)
    follow = data.get("follow") or {}
    if isinstance(follow, dict) and isinstance(follow.get("domains"), dict):
        return {"domains": follow.get("domains")}
    return data


def load_publish_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required to load publish config.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    publish = data.get("publish") or {}
    return publish if isinstance(publish, dict) else {}


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_arxiv_view_module():
    path = Path(__file__).resolve().parents[1] / "arxiv-view" / "arxiv_view.py"
    if not path.exists():
        raise RuntimeError(f"Missing arxiv-view module: {path}")
    return _load_module(path, "followhub_arxiv_view")


def infer_domains_for_arxiv_item(item: Dict[str, Any], domain_config: Dict[str, Any]) -> List[Dict[str, str]]:
    return [deepcopy(UNCATEGORIZED_DOMAIN)]


def importance_from_scores(item: Dict[str, Any]) -> str:
    overall = float(item.get("overall_score", 0) or 0)
    relevance = float(item.get("relevance_score", 0) or 0)
    if overall >= 2.8 or relevance >= 2.5:
        return "high"
    if overall >= 1.6 or relevance >= 1.2:
        return "medium"
    return "low"


def summary_from_arxiv_item(item: Dict[str, Any]) -> str:
    for key in ("one_liner_zh", "summary_cn", "abstract_en", "title"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "No summary available."


def build_digest_from_arxiv_input(input_path: Path, domain_config: Dict[str, Any]) -> Dict[str, Any]:
    module = load_arxiv_view_module()
    normalized = module.normalize_loaded_input(module.load_input(input_path))
    items = normalized.get("items") or []
    date = (
        (normalized.get("meta") or {}).get("days", [""])[0]
        if normalized.get("mode") != "search"
        else datetime.utcnow().strftime("%Y-%m-%d")
    )
    follow_items = []
    for item in items:
        follow_items.append(
            {
                "id": f"arxiv:{item.get('arxiv_id')}",
                "source_type": "arxiv",
                "title": item.get("title") or item.get("arxiv_id") or "Untitled",
                "summary": summary_from_arxiv_item(item),
                "importance": importance_from_scores(item),
                "domains": infer_domains_for_arxiv_item(item, domain_config),
                "authors": list(item.get("authors") or []),
                "categories": list(item.get("categories") or []),
                "author_meta": list(item.get("author_meta") or []),
                "first_affiliation": item.get("first_affiliation") or "",
                "hjfy_url": item.get("hjfy_url") or "",
                "published": item.get("published") or "",
                "updated": item.get("updated") or "",
                "abstract_en": item.get("abstract_en") or "",
                "one_liner_zh": item.get("one_liner_zh") or "",
                "summary_cn": item.get("summary_cn") or "",
                "hot_score": float(item.get("hot_score", 0) or 0),
                "overall_score": float(item.get("overall_score", 0) or 0),
                "relevance_score": float(item.get("relevance_score", 0) or 0),
                "is_favorite": bool(item.get("is_favorite", False)),
                "links": [
                    {"label": "Abs", "href": item.get("html_url")},
                    {"label": "PDF", "href": item.get("pdf_url")},
                    *(
                        [{"label": "Hjfy", "href": item.get("hjfy_url")}]
                        if item.get("hjfy_url")
                        else []
                    ),
                    *[
                        {"label": f"Code {index + 1}", "href": url}
                        for index, url in enumerate(item.get("code_urls") or [])
                    ],
                ],
            }
        )
    highlights = [
        f"{item['title']}: {item['summary']}"
        for item in sorted(follow_items, key=lambda x: IMPORTANCE_WEIGHT[x["importance"]], reverse=True)[:3]
    ]
    return validate_digest(
        {
            "date": date,
            "summary": f"arXiv digest with {len(follow_items)} paper(s) across normalized Follow domains.",
            "highlights": highlights,
            "counts": {"arxiv": len(follow_items), "wechat": 0, "x": 0, "bilibili": 0},
            "sections": [
                {
                    "source_type": "arxiv",
                    "title": "arXiv",
                    "items": follow_items,
                }
            ],
        }
    )




def flatten_items(digests: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for digest in digests:
        for section in digest.get("sections", []):
            for item in section.get("items", []):
                row = deepcopy(item)
                row["date"] = digest["date"]
                row["source_title"] = section["title"]
                rows.append(row)
    rows.sort(key=lambda item: (item["date"], IMPORTANCE_WEIGHT[item["importance"]]), reverse=True)
    return rows


def _published_item_rank(item: Dict[str, Any]) -> tuple:
    return (
        1 if _is_meaningful_chinese(item.get("summary_cn")) else 0,
        1 if _is_meaningful_chinese(item.get("one_liner_zh")) else 0,
        float(item.get("overall_score", 0) or 0),
        item.get("date") or "",
    )


def flatten_published_items(digests: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = flatten_items(digests)
    rows = [item for item in rows if item.get("include_in_follow", True)]
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        current = deduped.get(item_id)
        if current is None or _published_item_rank(item) > _published_item_rank(current):
            deduped[item_id] = item
    result = list(deduped.values())
    result.sort(key=lambda item: (item["date"], IMPORTANCE_WEIGHT[item["importance"]]), reverse=True)
    return result


def _is_meaningful_chinese(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def build_digest_highlights_from_sections(sections: Sequence[Dict[str, Any]]) -> List[str]:
    items = []
    for section in sections:
        items.extend(section.get("items", []))
    ranked = sorted(items, key=lambda item: (IMPORTANCE_WEIGHT[item["importance"]], item.get("overall_score", 0)), reverse=True)
    return [f"{item['title']}: {item['summary']}" for item in ranked[:3]]


def build_digest_summary(date_value: str, sections: Sequence[Dict[str, Any]], counts: Dict[str, int], original_summary: str) -> str:
    source_types = [section.get("source_type") for section in sections if section.get("count")]
    if source_types and all(source == "arxiv" for source in source_types):
        return f"{date_value} arXiv daily selected {counts.get('arxiv', 0)} papers for follow-up."
    return original_summary


def sanitize_digests_for_publication(digests: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_digests = [validate_digest(digest) for digest in digests]
    best_rank_by_id: Dict[str, tuple] = {}
    for item in flatten_published_items(normalized_digests):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        rank = _published_item_rank(item)
        current_rank = best_rank_by_id.get(item_id)
        if current_rank is None or rank > current_rank:
            best_rank_by_id[item_id] = rank

    sanitized_digests: List[Dict[str, Any]] = []
    for digest in normalized_digests:
        published_sections = []
        for section in digest.get("sections", []):
            published_items = []
            for item in section.get("items", []):
                if not item.get("include_in_follow", True):
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    continue
                item_with_date = deepcopy(item)
                item_with_date["date"] = digest["date"]
                item_rank = _published_item_rank(item_with_date)
                if best_rank_by_id.get(item_id) != item_rank:
                    continue
                candidate = deepcopy(item_with_date)
                published_items.append(candidate)
            published_sections.append(
                {
                    "source_type": section["source_type"],
                    "title": section["title"],
                    "count": len(published_items),
                    "items": published_items,
                }
            )

        sanitized = {
            "date": digest["date"],
            "sections": published_sections,
        }
        sanitized["counts"] = {
            source: sum(section["count"] for section in published_sections if section["source_type"] == source)
            for source in SOURCE_ORDER
        }
        sanitized["summary"] = build_digest_summary(
            digest["date"],
            published_sections,
            sanitized["counts"],
            digest["summary"],
        )
        sanitized["highlights"] = build_digest_highlights_from_sections(published_sections)
        sanitized_digests.append(validate_digest(sanitized))
    return sanitized_digests


def build_manifest(digests: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    domain_stats: Dict[str, Dict[str, Any]] = {}
    for item in flatten_published_items(digests):
        for domain in item.get("domains", []):
            stat = domain_stats.setdefault(
                domain["slug"],
                {"slug": domain["slug"], "name": domain["name"], "count": 0, "latest_date": ""},
            )
            stat["count"] += 1
            if item["date"] > stat["latest_date"]:
                stat["latest_date"] = item["date"]
    days = [
        {
            "date": digest["date"],
            "summary": digest["summary"],
            "counts": digest["counts"],
            "path": f"daily/{digest['date']}.json",
        }
        for digest in digests
    ]
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "latest_date": digests[0]["date"] if digests else "",
        "days": days,
        "sources": [
            {
                "source": source,
                "title": normalize_source_name(source),
                "count": sum(digest["counts"].get(source, 0) for digest in digests),
                "path": f"sources/{source}.json",
            }
            for source in SOURCE_ORDER
        ],
        "domains": sorted(domain_stats.values(), key=lambda item: (-item["count"], item["slug"])),
    }


def build_source_files(digests: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    rows = flatten_published_items(digests)
    files = {}
    for source in SOURCE_ORDER:
        items = [item for item in rows if item["source_type"] == source]
        files[f"sources/{source}.json"] = {
            "source": source,
            "title": normalize_source_name(source),
            "item_count": len(items),
            "items": items,
        }
        latest_date = items[0]["date"] if items else ""
        latest_time = datetime.fromisoformat(f"{latest_date}T00:00:00") if latest_date else None
        if latest_time is None:
            recent_items = []
        else:
            recent_items = []
            for item in items:
                item_time = datetime.fromisoformat(f"{item['date']}T00:00:00")
                days_diff = (latest_time - item_time).days
                if days_diff < RECENT_SOURCE_DAYS:
                    recent_items.append(item)
        files[f"sources/{source}-recent.json"] = {
            "source": source,
            "title": normalize_source_name(source),
            "scope": "recent",
            "window_days": RECENT_SOURCE_DAYS,
            "item_count": len(recent_items),
            "items": recent_items,
        }
        month_buckets: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            month = str(item.get("date") or "")[:7]
            if not month:
                continue
            month_buckets.setdefault(month, []).append(item)
        for month, month_items in month_buckets.items():
            files[f"sources/{source}-{month}.json"] = {
                "source": source,
                "title": normalize_source_name(source),
                "scope": "archive",
                "month": month,
                "item_count": len(month_items),
                "items": month_items,
            }
    return files


def build_domains_file(digests: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = flatten_published_items(digests)
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        for domain in item.get("domains", []):
            bucket = grouped.setdefault(
                domain["slug"],
                {
                    "slug": domain["slug"],
                    "name": domain["name"],
                    "count": 0,
                    "latest_date": "",
                    "highlights": [],
                },
            )
            bucket["count"] += 1
            bucket["latest_date"] = max(bucket["latest_date"], item["date"])
            if len(bucket["highlights"]) < 3 and item["title"] not in [highlight["title"] for highlight in bucket["highlights"]]:
                bucket["highlights"].append(
                    {"title": item["title"], "summary": item["summary"], "date": item["date"]}
                )
    return {"domains": sorted(grouped.values(), key=lambda item: (-item["count"], item["slug"]))}


def write_artifacts(digests: Sequence[Dict[str, Any]], output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(digests)
    latest = digests[0] if digests else {}
    source_files = build_source_files(digests)
    domains_file = build_domains_file(digests)

    save_json(output_dir / "manifest.json", manifest)
    save_json(output_dir / "latest.json", latest)
    save_json(output_dir / "domains.json", domains_file)
    for digest in digests:
        save_json(output_dir / "daily" / f"{digest['date']}.json", digest)
    for relative_path, payload in source_files.items():
        save_json(output_dir / relative_path, payload)
    return {
        "manifest": str(output_dir / "manifest.json"),
        "latest": str(output_dir / "latest.json"),
        "domains": str(output_dir / "domains.json"),
    }


def sync_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def merge_digests(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not existing:
        return validate_digest(incoming)
    merged = deepcopy(validate_digest(existing))
    next_digest = validate_digest(incoming)
    merged["summary"] = next_digest["summary"] or merged["summary"]
    merged["highlights"] = next_digest["highlights"] or merged["highlights"]

    sections_by_source = {section["source_type"]: deepcopy(section) for section in merged["sections"]}
    for next_section in next_digest["sections"]:
        source = next_section["source_type"]
        current = sections_by_source.get(source)
        if current is None:
            sections_by_source[source] = deepcopy(next_section)
            continue

        items_by_id = {item["id"]: deepcopy(item) for item in current["items"]}
        for item in next_section["items"]:
            items_by_id[item["id"]] = deepcopy(item)
        current["items"] = list(items_by_id.values())
        current["count"] = len(current["items"])
        current["title"] = next_section["title"] or current["title"]
        sections_by_source[source] = current

    merged["sections"] = [sections_by_source[source] for source in SOURCE_ORDER if source in sections_by_source]
    merged["counts"] = {
        source: sum(section["count"] for section in merged["sections"] if section["source_type"] == source)
        for source in SOURCE_ORDER
    }
    return merged


def load_rcli_module():
    path = Path(__file__).resolve().parents[1] / "rcli" / "scripts" / "rcli.py"
    if not path.exists():
        raise RuntimeError(f"Missing rcli module: {path}")
    return _load_module(path, "followhub_rcli")


def fetch_remote_json(rcli_module: Any, prefix: str, key: str) -> Optional[Dict[str, Any]]:
    config_path = rcli_module.resolve_config_path(None)
    config = rcli_module.load_rclone_config(config_path)
    target = rcli_module.remote_path(config, f"{prefix}/{key}")
    with rcli_module.temp_rclone_config(config) as temp_config_path:
        proc = rcli_module.run_rclone(temp_config_path, "cat", [target])
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        stdout = (proc.stdout or "").lower()
        if "not found" in stderr or "not found" in stdout or "directory not found" in stderr:
            return None
        rcli_module.fail_from_process(proc, "cat", target)
    text = (proc.stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def upload_artifacts_with_rcli(
    rcli_module: Any,
    config_path: Path,
    local_dir: Path,
    remote_prefix: str,
    include_paths: Optional[Sequence[str]] = None,
) -> List[str]:
    config = rcli_module.load_rclone_config(config_path)
    uploaded = []
    allowed = set(include_paths or [])
    for path in sorted(local_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(local_dir).as_posix()
        if allowed and relative not in allowed:
            continue
        key = f"{remote_prefix.rstrip('/')}/{relative}"
        target = rcli_module.remote_path(config, key)
        with rcli_module.temp_rclone_config(config) as temp_config_path:
            proc = rcli_module.run_rclone(temp_config_path, "copyto", [str(path), target])
        if proc.returncode != 0:
            rcli_module.fail_from_process(proc, "copyto", target)
        uploaded.append(key)
    return uploaded


def build_package(
    digests: Sequence[Dict[str, Any]],
    *,
    output_dir: Path,
    page_data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    public_digests = sanitize_digests_for_publication(digests)
    written = write_artifacts(public_digests, output_dir)
    if page_data_dir:
        sync_tree(output_dir, page_data_dir)
    return {
        "digest_count": len(public_digests),
        "latest_date": public_digests[0]["date"] if public_digests else "",
        "written": written,
        "page_data_dir": str(page_data_dir) if page_data_dir else "",
    }


def build_daily_command(
    *,
    input_paths: Sequence[Path],
    output_dir: Path,
    page_data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    digests = load_digests(input_paths)
    return build_package(digests, output_dir=output_dir, page_data_dir=page_data_dir)


def publish_daily_command(
    *,
    input_paths: Sequence[Path],
    remote_prefix: str,
    output_dir: Path,
    page_data_dir: Optional[Path] = None,
    allow_historical: bool = False,
) -> Dict[str, Any]:
    incoming_digests = load_digests(input_paths)
    if not incoming_digests:
        raise ValueError("No digest inputs provided")
    incoming = incoming_digests[0]
    today = datetime.now().strftime("%Y-%m-%d")
    if not allow_historical and incoming["date"] != today:
        raise ValueError(
            f"Refusing to publish historical daily digest {incoming['date']} in normal mode. "
            f"Today is {today}. Use maintenance mode to override."
        )

    rcli_module = load_rcli_module()
    config_path = rcli_module.resolve_config_path(None)

    existing_daily = fetch_remote_json(rcli_module, remote_prefix, f"daily/{incoming['date']}.json")
    merged_daily = merge_digests(existing_daily, incoming)

    remote_manifest = fetch_remote_json(rcli_module, remote_prefix, "manifest.json") or {}
    remote_days = [item.get("date") for item in remote_manifest.get("days", []) if item.get("date")]

    all_digests = [merged_daily]
    for day in remote_days:
        if day == incoming["date"]:
            continue
        remote_digest = fetch_remote_json(rcli_module, remote_prefix, f"daily/{day}.json")
        if remote_digest:
            all_digests.append(validate_digest(remote_digest))
    all_digests.sort(key=lambda item: item["date"], reverse=True)

    payload = build_package(all_digests, output_dir=output_dir, page_data_dir=page_data_dir)
    include_paths = None
    if not allow_historical:
        include_paths = [
            "domains.json",
            "latest.json",
            "manifest.json",
            f"daily/{incoming['date']}.json",
        ]
        include_paths.extend(
            path.relative_to(output_dir).as_posix()
            for path in sorted((output_dir / "sources").glob("*.json"))
        )
    uploaded = upload_artifacts_with_rcli(
        rcli_module,
        config_path,
        output_dir,
        remote_prefix,
        include_paths=include_paths,
    )
    payload["uploaded"] = uploaded
    payload["merged_date"] = incoming["date"]
    return payload


def rebuild_index_command(
    *,
    daily_dir: Path,
    output_dir: Path,
    page_data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    digests = load_digests_from_directory(daily_dir)
    return build_package(digests, output_dir=output_dir, page_data_dir=page_data_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="follow-publish")
    subparsers = parser.add_subparsers(dest="command")

    build_daily = subparsers.add_parser("build-daily")
    build_daily.add_argument("--input", action="append", required=True)
    build_daily.add_argument("--output-dir", required=True)
    build_daily.add_argument("--page-data-dir")
    build_daily.add_argument("--config")

    build_from_arxiv = subparsers.add_parser("build-from-arxiv")
    build_from_arxiv.add_argument("--input", required=True)
    build_from_arxiv.add_argument("--output-dir", required=True)
    build_from_arxiv.add_argument("--page-data-dir")
    build_from_arxiv.add_argument("--domain-config")
    build_from_arxiv.add_argument("--config")

    publish_daily = subparsers.add_parser("publish-daily")
    publish_daily.add_argument("--input", action="append", required=True)
    publish_daily.add_argument("--remote-prefix", default="follow")
    publish_daily.add_argument("--output-dir", required=True)
    publish_daily.add_argument("--page-data-dir")
    publish_daily.add_argument("--config")
    publish_daily.add_argument(
        "--allow-historical",
        action="store_true",
        help="Maintenance-only override that allows publishing non-today daily digests.",
    )

    rebuild_index = subparsers.add_parser("rebuild-index")
    rebuild_index.add_argument("--daily-dir", required=True)
    rebuild_index.add_argument("--output-dir", required=True)
    rebuild_index.add_argument("--page-data-dir")
    rebuild_index.add_argument("--config")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build-daily":
        publish_config = load_publish_config(Path(args.config)) if getattr(args, "config", None) else {}
        payload = build_daily_command(
            input_paths=[Path(path) for path in args.input],
            output_dir=Path(args.output_dir),
            page_data_dir=Path(args.page_data_dir or publish_config.get("page_data_dir")) if (args.page_data_dir or publish_config.get("page_data_dir")) else None,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "build-from-arxiv":
        config_path = Path(args.config) if getattr(args, "config", None) else None
        publish_config = load_publish_config(config_path) if config_path else {}
        domain_config = load_domain_config(Path(args.domain_config)) if args.domain_config else load_domain_config(config_path) if config_path else deepcopy(DEFAULT_DOMAIN_CONFIG)
        digest = build_digest_from_arxiv_input(Path(args.input), domain_config)
        payload = build_package(
            [digest],
            output_dir=Path(args.output_dir),
            page_data_dir=Path(args.page_data_dir or publish_config.get("page_data_dir")) if (args.page_data_dir or publish_config.get("page_data_dir")) else None,
        )
        save_json(Path(args.output_dir) / "daily-digest.json", digest)
        payload["daily_digest"] = str(Path(args.output_dir) / "daily-digest.json")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "publish-daily":
        publish_config = load_publish_config(Path(args.config)) if getattr(args, "config", None) else {}
        payload = publish_daily_command(
            input_paths=[Path(path) for path in args.input],
            remote_prefix=args.remote_prefix or publish_config.get("remote_prefix") or "follow",
            output_dir=Path(args.output_dir),
            page_data_dir=Path(args.page_data_dir or publish_config.get("page_data_dir")) if (args.page_data_dir or publish_config.get("page_data_dir")) else None,
            allow_historical=bool(args.allow_historical),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rebuild-index":
        publish_config = load_publish_config(Path(args.config)) if getattr(args, "config", None) else {}
        payload = rebuild_index_command(
            daily_dir=Path(args.daily_dir),
            output_dir=Path(args.output_dir),
            page_data_dir=Path(args.page_data_dir or publish_config.get("page_data_dir")) if (args.page_data_dir or publish_config.get("page_data_dir")) else None,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
