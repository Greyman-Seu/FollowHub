#!/usr/bin/env python3
"""
update_wiki.py - Scan llm-wiki source notes and surface candidates for topic/synthesis updates.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SourceDigest:
    slug: str
    title: str
    publish_date: str
    source_url: str
    keywords: List[str]
    related_topics: List[str]
    tldr: str
    intuition: str


@dataclass
class UpdateRecommendation:
    source_count: int
    should_create_topic: bool
    should_create_synthesis: bool
    recommendation: str


def parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    frontmatter_text, body = parts
    lines = frontmatter_text.splitlines()[1:]
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_key:
            existing = data.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(stripped[2:].strip().strip('"'))
            continue
        if ":" not in line:
            current_key = None
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        clean_value = value.strip().strip('"')
        data[current_key] = [] if clean_value == "" else clean_value
    return data, body


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[-\s]+", "-", value, flags=re.UNICODE).strip("-")
    return value or "source"


def extract_section(body: str, title: str) -> str:
    pattern = rf"^##\s+{re.escape(title)}\s*$"
    match = re.search(pattern, body, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def parse_source(path: Path) -> SourceDigest:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    title = str(frontmatter.get("title") or path.stem)
    slug = slugify(title)
    keywords = frontmatter.get("keywords") if isinstance(frontmatter.get("keywords"), list) else []
    related_topics = frontmatter.get("related_topics") if isinstance(frontmatter.get("related_topics"), list) else []
    return SourceDigest(
        slug=slug,
        title=title,
        publish_date=str(frontmatter.get("publish_date") or ""),
        source_url=str(frontmatter.get("source_url") or ""),
        keywords=keywords,
        related_topics=related_topics,
        tldr=extract_section(body, "太长不看"),
        intuition=extract_section(body, "直观理解"),
    )


def scan_sources(wiki_root: Path) -> List[SourceDigest]:
    sources_dir = wiki_root / "wiki" / "sources"
    if not sources_dir.is_dir():
        return []
    notes = sorted(sources_dir.glob("*.md"))
    return [parse_source(note) for note in notes]


def build_recommendation(digests: List[SourceDigest]) -> UpdateRecommendation:
    count = len(digests)
    if count < 3:
        return UpdateRecommendation(
            source_count=count,
            should_create_topic=False,
            should_create_synthesis=False,
            recommendation="当前 source 数量较少，建议继续积累来源笔记，暂不新建 topic 或 synthesis。",
        )
    if count < 6:
        return UpdateRecommendation(
            source_count=count,
            should_create_topic=True,
            should_create_synthesis=False,
            recommendation="已经有一定来源积累，建议优先梳理重复主题并尝试创建或更新 topic 页。",
        )
    return UpdateRecommendation(
        source_count=count,
        should_create_topic=True,
        should_create_synthesis=True,
        recommendation="来源积累已较丰富，建议同时检查 topic 聚类和 synthesis 候选。",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan llm-wiki sources and produce a lightweight update queue.")
    parser.add_argument("--wiki-root", required=True, help="llm-wiki root path")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of source digests to print")
    parser.add_argument("--print-json", action="store_true", help="Print machine-readable JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    digests = scan_sources(wiki_root)[: args.limit]
    recommendation = build_recommendation(digests)
    if args.print_json:
        print(
            json.dumps(
                {
                    "sources": [asdict(item) for item in digests],
                    "recommendation": asdict(recommendation),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    for item in digests:
        print(f"- {item.title}")
        print(f"  slug: {item.slug}")
        print(f"  publish_date: {item.publish_date}")
        if item.keywords:
            print(f"  keywords: {', '.join(item.keywords)}")
        if item.related_topics:
            print(f"  related_topics: {', '.join(item.related_topics)}")
        if item.tldr:
            print(f"  tldr: {item.tldr}")
    print("")
    print("Recommendation:")
    print(f"- source_count: {recommendation.source_count}")
    print(f"- should_create_topic: {str(recommendation.should_create_topic).lower()}")
    print(f"- should_create_synthesis: {str(recommendation.should_create_synthesis).lower()}")
    print(f"- note: {recommendation.recommendation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
