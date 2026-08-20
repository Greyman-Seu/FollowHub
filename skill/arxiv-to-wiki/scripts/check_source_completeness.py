#!/usr/bin/env python3
"""Check arxiv-to-wiki source-note completeness.

This is intentionally lightweight: it catches missing fields that break downstream
wiki pages, especially labeled risk fields that must survive Markdown -> JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_SECTIONS = [
    "太长不看",
    "直观理解",
    "核心信息",
    "背景与问题",
    "论文摘要（英文原文）",
    "论文摘要（中文翻译）",
    "方法",
    "结果",
    "洞察",
    "风险与判断",
    "相关主题",
]

FRONTMATTER_ANY = {
    "source type": ["source_type", "material_type"],
    "source url": ["source_url", "source_input", "links"],
    "date": ["date", "publish_date", "created"],
    "domain": ["domains", "domain", "domain_slugs", "primary_domain_slug"],
    "tags": ["tags"],
    "related topics": ["related_topics"],
    "status": ["status"],
}

RISK_LABELS = {
    "riskLimitations": ["局限", "限制", "Limitations"],
    "riskScenarios": ["适用场景", "适用", "Application Scenarios", "Use Cases"],
    "riskJudgment": ["最终判断", "判断", "Final Judgment", "Verdict"],
}

STRUCTURED_TEXT_BLOCKS = {
    "backgroundMotivation": ("背景与问题", ["动机", "为什么做", "Motivation"], 60),
    "backgroundGap": ("背景与问题", ["问题缺口", "Gap"], 60),
    "methodOverview": ("方法", ["方法概述", "Overview"], 80),
    "methodCore": ("方法", ["核心机制", "Core Mechanism"], 80),
}

STRUCTURED_LIST_BLOCKS = {
    "methodBreakdown": ("方法", ["方法拆解", "Breakdown"], 3),
    "methodTakeaways": ("方法", ["关键要点", "Key Takeaways"], 2),
}

JSON_REQUIRED_ARRAYS = {
    "riskLimitations": 1,
    "riskScenarios": 1,
    "riskJudgment": 1,
    "methodBreakdown": 3,
    "methodTakeaways": 2,
}
JSON_REQUIRED_TEXT = ["tldr", "method", "risks", "sourceUrl"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check one or more wiki source notes for required arxiv-to-wiki fields.")
    parser.add_argument("--wiki-root", required=True, help="Wiki root containing wiki/sources")
    parser.add_argument("--package-dir", default="", help="Optional built FollowHub wiki package directory")
    parser.add_argument("--slug", action="append", default=[], help="Source slug to check; repeatable")
    parser.add_argument("--all", action="store_true", help="Check all source notes")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def strip_markdown(value: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", str(value or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[>\-*]\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def meaningful_length(value: str) -> int:
    return len(re.sub(r"\s+", "", strip_markdown(value)))


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    return text[4:end], text[end + 5 :].lstrip("\n")


def frontmatter_has(frontmatter: str, keys: list[str]) -> bool:
    for key in keys:
        if re.search(rf"^\s*{re.escape(key)}\s*:", frontmatter, re.MULTILINE):
            return True
    return False


def section_after_heading(body: str, heading: str) -> str:
    lines = body.splitlines()
    capture = False
    out: list[str] = []
    for line in lines:
        if line.startswith("## ") and line[3:].strip().lower() == heading.strip().lower():
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def normalize_label(value: str) -> str:
    return re.sub(r"[\s:：]+", "", str(value or "").strip().lower())


def extract_labeled_block(section: str, labels: list[str]) -> str:
    wanted = {normalize_label(label) for label in labels}
    capture = False
    out: list[str] = []
    for line in section.splitlines():
        heading_match = re.match(r"^\s*#{3,6}\s+(.+?)\s*#*\s*$", line)
        if heading_match:
            label = normalize_label(strip_markdown(heading_match.group(1)))
            if label in wanted:
                capture = True
                out = []
                continue
            if capture:
                break
        match = re.match(r"^\s*\*\*([^*]+?)\s*[:：]?\*\*\s*(.*)$", line)
        if match:
            label = normalize_label(match.group(1))
            tail = match.group(2).strip()
            if label in wanted:
                capture = True
                out = [tail] if tail else []
                continue
            if capture:
                break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def split_list_items(value: str) -> list[str]:
    items: list[str] = []
    for line in str(value or "").splitlines():
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if match and strip_markdown(match.group(1)):
            items.append(strip_markdown(match.group(1)))
    return items


def source_paths(wiki_root: Path, slugs: list[str], check_all: bool) -> list[Path]:
    source_dir = wiki_root / "wiki" / "sources"
    if check_all:
        return sorted(source_dir.glob("*.md"))
    return [source_dir / f"{slug}.md" for slug in slugs]


def check_markdown(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.exists():
        return [f"missing source note: {path}"], warnings

    frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    if not frontmatter:
        errors.append("missing frontmatter")
    for label, keys in FRONTMATTER_ANY.items():
        if not frontmatter_has(frontmatter, keys):
            errors.append(f"missing frontmatter field group: {label} ({', '.join(keys)})")

    title = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if not title:
        errors.append("missing H1 title")

    for heading in REQUIRED_SECTIONS:
        section = section_after_heading(body, heading)
        if not strip_markdown(section):
            errors.append(f"missing or empty section: {heading}")

    for field, (heading, labels, minimum) in STRUCTURED_TEXT_BLOCKS.items():
        section = section_after_heading(body, heading)
        block = extract_labeled_block(section, labels)
        actual = meaningful_length(block)
        if actual < minimum:
            errors.append(
                f"structured block {field} is missing or too short: "
                f"{actual} meaningful character(s), need at least {minimum}"
            )

    for field, (heading, labels, minimum) in STRUCTURED_LIST_BLOCKS.items():
        section = section_after_heading(body, heading)
        block = extract_labeled_block(section, labels)
        actual = len(split_list_items(block))
        if actual < minimum:
            errors.append(
                f"structured list {field} has {actual} item(s), need at least {minimum}"
            )

    risk_section = section_after_heading(body, "风险与判断")
    for field, labels in RISK_LABELS.items():
        block = extract_labeled_block(risk_section, labels)
        if not strip_markdown(block):
            errors.append(f"missing or empty risk labeled block for {field}: {' / '.join(labels)}")

    if not re.search(r"!\[[^\]]*\]\([^)]+\)", body):
        warnings.append("no figures found in note body")
    return errors, warnings


def check_package_json(package_dir: Path, slug: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = package_dir / "source" / f"{slug}.json"
    if not path.exists():
        return [f"missing package source JSON: {path}"], warnings
    data = json.loads(path.read_text(encoding="utf-8"))

    for key in JSON_REQUIRED_TEXT:
        if not str(data.get(key) or "").strip():
            errors.append(f"package JSON missing text field: {key}")
    for key, minimum in JSON_REQUIRED_ARRAYS.items():
        value = data.get(key)
        actual = len([item for item in value if str(item).strip()]) if isinstance(value, list) else 0
        if actual < minimum:
            errors.append(f"package JSON array field {key} has {actual} item(s), need at least {minimum}")

    for key, (_, _, minimum) in STRUCTURED_TEXT_BLOCKS.items():
        actual = meaningful_length(str(data.get(key) or ""))
        if actual < minimum:
            errors.append(
                f"package JSON text field {key} is missing or too short: "
                f"{actual} meaningful character(s), need at least {minimum}"
            )

    source_url = str(data.get("sourceUrl") or data.get("htmlUrl") or "")
    if "arxiv.org" in source_url:
        for key in ["htmlUrl", "pdfUrl", "translationUrl"]:
            if not str(data.get(key) or "").strip():
                warnings.append(f"arXiv source package JSON missing optional but expected field: {key}")
    if not data.get("figureGallery"):
        warnings.append("package JSON has no figureGallery")
    return errors, warnings


def main() -> int:
    args = parse_args()
    wiki_root = Path(args.wiki_root)
    package_dir = Path(args.package_dir) if args.package_dir else None
    slugs = args.slug
    if not args.all and not slugs:
        print("ERROR: provide --slug or --all", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for path in source_paths(wiki_root, slugs, args.all):
        slug = path.stem
        errors, warnings = check_markdown(path)
        if package_dir:
            package_errors, package_warnings = check_package_json(package_dir, slug)
            errors.extend(package_errors)
            warnings.extend(package_warnings)
        results.append({"slug": slug, "path": str(path), "errors": errors, "warnings": warnings})

    ok = all(not item["errors"] for item in results)
    payload = {"ok": ok, "checked": len(results), "results": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            status = "OK" if not item["errors"] else "FAIL"
            print(f"{status} {item['slug']}")
            for error in item["errors"]:
                print(f"  ERROR: {error}")
            for warning in item["warnings"]:
                print(f"  WARN: {warning}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
