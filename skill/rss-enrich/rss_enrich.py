#!/usr/bin/env python3
"""Enrich RSS items and expose agent completion tasks for missing Chinese fields."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


HELP_TEXT = """\
rss-enrich: Enrich RSS items into the shared FollowHub contract.

Usage:
    rss-enrich help
    rss-enrich enrich --input rss-daily-output/2026-05-12/filter_input.json --output rss-daily-output/2026-05-12/enrich_results.json
"""

URL_PAT = re.compile(r"https?://[^\\s)\\]>\\'\"`]+", re.IGNORECASE)
PERSON_SPLIT_PAT = re.compile(r"[，,;；、/|]")
ORG_HINTS = (
    "university",
    "institute",
    "school",
    "college",
    "department",
    "laboratory",
    "lab",
    "research",
    "academy",
    "hospital",
    "公司",
    "大学",
    "学院",
    "实验室",
    "研究院",
)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dedup_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def extract_links(text: str) -> List[str]:
    return dedup_keep_order(match.group(0) for match in URL_PAT.finditer(text or ""))


def build_summary_prompt(title: str, content_text: str, summary: str, source_type: str) -> str:
    body = content_text.strip() or summary.strip()
    source = str(source_type or "rss").strip().lower()
    source_rules = (
        "- For X/Twitter: write like a human editor, keep the key actor / product / claim / result, and avoid empty labels such as '分享了一条动态'\n"
        "- For X/Twitter: `one_liner_zh` should usually be one compact Chinese sentence with concrete information\n"
        "- For WeChat: `one_liner_zh` should not repeat the title; extract the real takeaway\n"
        "- For WeChat: `summary_cn` should be 1-2 informative Chinese sentences, not a slogan\n"
        if source in {"x", "wechat"}
        else ""
    )
    return (
        "Read the following RSS item content and produce Chinese fields.\n\n"
        "Required output keys:\n"
        "- summary_cn: a faithful Chinese summary of the content\n"
        "- one_liner_zh: one concise Chinese line for quick scanning\n\n"
        "Rules:\n"
        "- Do not invent facts beyond the content\n"
        "- Keep summary_cn faithful rather than rewriting it into opinionated commentary\n"
        "- Keep one_liner_zh short and direct\n\n"
        f"{source_rules}"
        f"Source type: {source}\n\n"
        f"Title: {title}\n\n"
        f"Content: {body}\n"
    )


def build_entity_prompt(title: str, content_text: str, summary: str) -> str:
    body = content_text.strip() or summary.strip()
    return (
        "Read the following RSS item content and extract entities.\n\n"
        "Required output keys:\n"
        "- related_organizations: a list of institution/company/lab names directly tied to the item\n"
        "- related_companies: a list of company or industry lab names from related_organizations\n"
        "- key_people: a list of important people directly tied to the item, such as authors, speakers, founders, or cited researchers\n\n"
        "Rules:\n"
        "- Do not invent facts beyond the content\n"
        "- Only keep entities explicitly supported by the content\n"
        "- Normalize organization names and people names when obvious\n"
        "- Return empty lists if the content does not expose them clearly\n\n"
        f"Title: {title}\n\n"
        f"Content: {body}\n"
    )


def dedup_strings(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def normalize_people(value: Any) -> List[str]:
    if isinstance(value, list):
        return dedup_strings(value)
    if isinstance(value, str):
        return dedup_strings(part.strip() for part in PERSON_SPLIT_PAT.split(value) if part.strip())
    return []


def normalize_organizations(value: Any) -> List[str]:
    if isinstance(value, list):
        return dedup_strings(value)
    if isinstance(value, str):
        return dedup_strings(part.strip() for part in re.split(r"[;；、|\n]+", value) if part.strip())
    return []


def infer_organizations(text: str) -> List[str]:
    candidates = []
    for line in re.split(r"[\n。！？!?]", text or ""):
        value = line.strip()
        lowered = value.lower()
        if value and any(hint in lowered or hint in value for hint in ORG_HINTS):
            candidates.append(value[:120].strip(" ,;:"))
    return dedup_strings(candidates)[:4]


def needs_agent_summary(
    source_type: str,
    *,
    one_liner_zh: str,
    summary_cn: str,
    summary_generated_by: str,
) -> bool:
    source = str(source_type or "rss").strip().lower()
    marker = str(summary_generated_by or "").strip().lower()
    if source == "x":
        return not (marker == "agent" and one_liner_zh)
    if source == "wechat":
        return not (marker == "agent" and one_liner_zh and summary_cn)
    return not (one_liner_zh and summary_cn)


def enrich_item(item: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(item)
    source_type = str(enriched.get("source_type") or "rss").strip().lower()
    title = str(enriched.get("title") or "")
    content_text = str(enriched.get("content_text") or "")
    summary = str(enriched.get("summary") or "")
    one_liner_zh = str(enriched.get("one_liner_zh") or "").strip()
    summary_cn = str(enriched.get("summary_cn") or "").strip()
    summary_generated_by = str(enriched.get("summary_generated_by") or "").strip()
    links = dedup_keep_order(list(enriched.get("links") or []) + extract_links(content_text) + extract_links(summary))
    related_organizations = normalize_organizations(enriched.get("related_organizations"))
    if not related_organizations:
        related_organizations = infer_organizations(content_text or summary)
    related_companies = normalize_organizations(enriched.get("related_companies"))
    key_people = normalize_people(enriched.get("key_people") or enriched.get("authors"))
    enriched["links"] = links
    enriched["one_liner_zh"] = one_liner_zh
    enriched["summary_cn"] = summary_cn
    enriched["related_organizations"] = related_organizations
    enriched["related_companies"] = related_companies
    enriched["key_people"] = key_people
    enriched["summary_generated_by"] = summary_generated_by
    enriched["needs_agent_summary"] = needs_agent_summary(
        source_type,
        one_liner_zh=one_liner_zh,
        summary_cn=summary_cn,
        summary_generated_by=summary_generated_by,
    )
    enriched["needs_related_entities"] = not (related_organizations or key_people)
    enriched["agent_summary_prompt"] = build_summary_prompt(title, content_text, summary, source_type) if enriched["needs_agent_summary"] else ""
    enriched["agent_entity_prompt"] = build_entity_prompt(title, content_text, summary) if enriched["needs_related_entities"] else ""
    return enriched


def build_agent_completion(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks = []
    for entry in entries:
        if not entry.get("needs_agent_summary"):
            continue
        tasks.append(
            {
                "id": str(entry.get("id") or ""),
                "title": str(entry.get("title") or ""),
                "agent_summary_prompt": str(entry.get("agent_summary_prompt") or ""),
                "agent_entity_prompt": str(entry.get("agent_entity_prompt") or ""),
                "expected_output_schema": {
                    "id": str(entry.get("id") or ""),
                    "one_liner_zh": "string",
                    "summary_cn": "string",
                    "summary_generated_by": "agent",
                    "related_organizations": ["string"],
                    "related_companies": ["string"],
                    "key_people": ["string"],
                },
            }
        )
    return {
        "required": bool(tasks),
        "task_count": len(tasks),
        "recommended_batch_size": 3,
        "recommended_worker": "rss-enrich-agent-completion",
        "tasks": tasks,
    }


def enrich_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    entries = [enrich_item(entry) for entry in (payload.get("items") or payload.get("entries") or [])]
    return {
        "mode": "rss-enriched",
        "item_count": len(entries),
        "entries": entries,
        "agent_completion": build_agent_completion(entries),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-enrich")
    subparsers = parser.add_subparsers(dest="command")
    enrich = subparsers.add_parser("enrich")
    enrich.add_argument("--input", required=True)
    enrich.add_argument("--output", required=True)
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
    if args.command == "enrich":
        payload = load_json(Path(args.input))
        enriched = enrich_payload(payload)
        save_json(Path(args.output), enriched)
        agent_completion = enriched.get("agent_completion") or {}
        print(
            json.dumps(
                {
                    "mode": "rss-enriched",
                    "output": args.output,
                    "agent_completion_required": bool(agent_completion.get("required", False)),
                    "agent_completion_task_count": int(agent_completion.get("task_count", 0) or 0),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
