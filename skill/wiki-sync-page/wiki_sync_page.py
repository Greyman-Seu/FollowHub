#!/usr/bin/env python3
"""
wiki_sync_page.py - Inspect and stage public llm-wiki content for website sync.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


HELP_TEXT = """\
wiki-sync-page: inspect and stage llm-wiki content for website sync.

Usage:
    wiki-sync-page help
    wiki-sync-page inspect --wiki-root /path/to/wiki --page-root /path/to/site
    wiki-sync-page sync --wiki-root /path/to/wiki --page-root /path/to/site
"""


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PyYAML is required to read config files: {exc}") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {}


def get_nested(data: Dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


@dataclass
class SyncManifest:
    wiki_root: str
    page_root: str
    sources: List[str]
    topics: List[str]
    synthesis: List[str]
    graph_assets: List[str]


@dataclass
class ParsedWikiSource:
    slug: str
    title: str
    sourceType: str
    sourceUrl: str
    htmlUrl: str
    pdfUrl: str
    codeUrl: str
    translationUrl: str
    publishDate: str
    authors: List[str]
    affiliation: str
    relatedOrganizations: List[str]
    relatedCompanies: List[str]
    keywords: List[str]
    primaryDomainSlug: str
    domainSlugs: List[str]
    heroImage: str
    tldr: str
    intuition: str
    abstractEn: str
    abstractZh: str
    background: str
    backgroundMotivation: str
    backgroundGap: str
    method: str
    methodOverview: str
    methodCore: str
    methodBreakdown: List[str]
    methodTakeaways: List[str]
    results: str
    resultHighlights: List[str]
    insights: str
    insightCore: List[str]
    insightRelations: List[str]
    insightBorrowable: List[str]
    risks: str
    riskLimitations: List[str]
    riskScenarios: List[str]
    riskJudgment: List[str]
    resultsTableMarkdown: str
    resultsTable: Dict[str, Any]
    figureGallery: List[Dict[str, str]]
    relatedTopicSlugs: List[str]


@dataclass
class ParsedWikiTopic:
    slug: str
    title: str
    domain: str
    summary: str
    body: str
    tags: List[str]
    created: str
    updated: str
    sourceTitles: List[str]
    relatedPages: List[str]


@dataclass
class ParsedWikiSynthesis:
    slug: str
    title: str
    summary: str
    body: str
    tags: List[str]
    created: str
    updated: str
    sourceTitles: List[str]
    relatedPages: List[str]


def resolve_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    payload: Dict[str, Any] = {}
    if args.config:
        config_path = Path(args.config).expanduser().resolve()
        payload = load_yaml(config_path)

    wiki_root = args.wiki_root or get_nested(payload, "wiki", "root")
    page_root = args.page_root or get_nested(payload, "page", "root")
    if not wiki_root:
        raise RuntimeError("Missing wiki root. Pass --wiki-root or configure wiki.root.")
    if not page_root:
        raise RuntimeError("Missing page root. Pass --page-root or configure page.root.")
    return Path(str(wiki_root)).expanduser().resolve(), Path(str(page_root)).expanduser().resolve()


def list_markdown(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    return sorted(str(path) for path in directory.glob("*.md") if path.is_file())


def list_graph_assets(wiki_root: Path) -> List[str]:
    wiki_dir = wiki_root / "wiki"
    if not wiki_dir.is_dir():
        return []
    names = [
        "knowledge-graph.html",
        "graph-data.json",
        "d3.min.js",
        "rough.min.js",
        "marked.min.js",
        "purify.min.js",
        "graph-wash.js",
        "graph-wash-helpers.js",
    ]
    assets: List[str] = []
    for name in names:
        path = wiki_dir / name
        if path.exists():
            assets.append(str(path))
    return assets


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


def resolve_frontmatter_slug(frontmatter: Dict[str, Any], fallback: str) -> str:
    for key in ("slug", "id"):
        raw = str(frontmatter.get(key) or "").strip()
        if raw:
            return raw
    return slugify(fallback)


def extract_section(body: str, title: str) -> str:
    pattern = rf"^##\s+{re.escape(title)}\s*$"
    match = re.search(pattern, body, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def first_image_url(text: str) -> str:
    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", text)
    return match.group(1).strip() if match else ""


def extract_labeled_block(text: str, label: str) -> str:
    pattern = rf"\*\*{re.escape(label)}：\*\*\s*(.*?)(?=\n\*\*|$)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_bullets(text: str) -> List[str]:
    return [line[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]


def classify_figures(*sections: tuple[str, str]) -> List[Dict[str, str]]:
    figures: List[Dict[str, str]] = []
    for zone, text in sections:
        for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
            figures.append(
                {
                    "zone": zone,
                    "caption": match.group(1).strip(),
                    "src": match.group(2).strip(),
                }
            )
    return figures


def parse_markdown_table(text: str) -> Dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) < 2:
        return {"columns": [], "rows": []}
    columns = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows: List[List[str]] = []
    for line in table_lines[2:]:
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return {"columns": columns, "rows": rows}


def normalize_slug_list(values: Any, fallback: Optional[str] = None, limit: int = 2) -> List[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = [str(value) for value in values]
    else:
        raw_values = []
    if fallback:
        raw_values.insert(0, fallback)

    result: List[str] = []
    for raw in raw_values:
        value = raw.strip()
        lowered = value.lower()
        if not value or lowered == "none" or value.startswith("暂无") or lowered.startswith("no related"):
            continue
        slug = slugify(value)
        if slug and slug not in result:
            result.append(slug)
        if len(result) >= limit:
            break
    return result


def derive_hjfy_url(*urls: str) -> str:
    for url in urls:
        match = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", url, re.IGNORECASE)
        if match:
            return f"https://hjfy.top/arxiv/{match.group(1)}"
    return ""


ORG_SPLIT_PATTERN = re.compile(r"[;；、\n]+")
COMPANY_NAME_MARKERS = (
    "DeepMind",
    "Google",
    "NVIDIA",
    "Physical Intelligence",
    "Toyota Research Institute",
    "OpenAI",
    "Microsoft",
    "Meta",
    "Apple",
    "Amazon",
    "Anthropic",
    "xAI",
    "Huawei",
    "Tencent",
    "Alibaba",
    "ByteDance",
    "Baidu",
    "Tesla",
)


def normalize_label_list(values: Any) -> List[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = [str(value) for value in values]
    else:
        raw_values = []

    labels: List[str] = []
    for raw in raw_values:
        for part in ORG_SPLIT_PATTERN.split(str(raw)):
            value = part.strip().strip('"')
            if not value or value.lower() in {"none", "n/a", "unknown"} or value.startswith("暂无"):
                continue
            if value not in labels:
                labels.append(value)
    return labels


def infer_related_companies(organizations: List[str]) -> List[str]:
    companies: List[str] = []
    for organization in organizations:
        if any(marker.lower() in organization.lower() for marker in COMPANY_NAME_MARKERS):
            if organization not in companies:
                companies.append(organization)
    return companies


def extract_body_affiliation_hint(body: str) -> str:
    patterns = [
        r"[-*]\s*\*\*(?:作者单位|机构|单位)：\*\*\s*([^\n]+)",
        r"[-*]\s*\*\*(?:Affiliation|Affiliations)：\*\*\s*([^\n]+)",
        r"[-*]\s*\*\*(?:Affiliation|Affiliations)\*\*:\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def parse_note_source(path: Path) -> ParsedWikiSource:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    title = str(frontmatter.get("title") or path.stem)
    slug = resolve_frontmatter_slug(frontmatter, title)
    tldr = extract_section(body, "太长不看")
    intuition = extract_section(body, "直观理解")
    background = extract_section(body, "背景与问题")
    abstract_en = extract_section(body, "论文摘要（英文原文）")
    abstract_zh = extract_section(body, "论文摘要（中文翻译）")
    method = extract_section(body, "方法")
    results = extract_section(body, "结果")
    insights = extract_section(body, "洞察")
    risks = extract_section(body, "风险与判断")
    results_table = extract_section(body, "结果速览表")
    related_topics_section = extract_section(body, "相关主题")
    section_related_topics = [
        line[2:].strip().rstrip(".")
        for line in related_topics_section.splitlines()
        if line.strip().startswith("- ")
    ]
    related_topics = normalize_slug_list(frontmatter.get("related_topics"), limit=2) or normalize_slug_list(section_related_topics, limit=2)
    images = frontmatter.get("images") if isinstance(frontmatter.get("images"), list) else []
    hero_image = first_image_url(intuition) or (images[0] if images else "")
    figures = classify_figures(("method", method), ("results", results), ("insights", insights), ("risks", risks))
    parsed_results_table = parse_markdown_table(results_table)
    primary_domain = str(
        frontmatter.get("primary_domain_slug")
        or frontmatter.get("primary_domain")
        or frontmatter.get("domain")
        or ""
    )
    domain_slugs = normalize_slug_list(
        frontmatter.get("domain_slugs") or frontmatter.get("domains"),
        fallback=primary_domain,
    )
    primary_domain_slug = slugify(primary_domain) if primary_domain else (domain_slugs[0] if domain_slugs else "")
    raw_keywords = frontmatter.get("keywords")
    if not isinstance(raw_keywords, list) or not raw_keywords:
        raw_keywords = frontmatter.get("tags")
    keywords = raw_keywords if isinstance(raw_keywords, list) else []
    source_url = str(frontmatter.get("source_url") or "")
    html_url = str(frontmatter.get("html_url") or "")
    pdf_url = str(frontmatter.get("pdf_url") or "")
    translation_url = str(frontmatter.get("translation_url") or "") or derive_hjfy_url(source_url, html_url, pdf_url)
    body_affiliation_hint = extract_body_affiliation_hint(body)
    affiliation_labels = normalize_label_list([frontmatter.get("affiliation") or "", body_affiliation_hint])
    affiliation = affiliation_labels[0] if affiliation_labels else ""
    related_organizations = normalize_label_list(
        frontmatter.get("related_organizations") or frontmatter.get("relatedOrganizations")
    )
    if not related_organizations:
        related_organizations = affiliation_labels
    related_companies = normalize_label_list(
        frontmatter.get("related_companies") or frontmatter.get("relatedCompanies")
    )
    if not related_companies:
        related_companies = infer_related_companies(related_organizations)

    return ParsedWikiSource(
        slug=slug,
        title=title,
        sourceType=str(frontmatter.get("source_type") or "paper"),
        sourceUrl=source_url,
        htmlUrl=html_url,
        pdfUrl=pdf_url,
        codeUrl=str(frontmatter.get("code_url") or ""),
        translationUrl=translation_url,
        publishDate=str(frontmatter.get("publish_date") or ""),
        authors=frontmatter.get("authors") if isinstance(frontmatter.get("authors"), list) else [],
        affiliation=affiliation,
        relatedOrganizations=related_organizations,
        relatedCompanies=related_companies,
        keywords=keywords,
        primaryDomainSlug=primary_domain_slug,
        domainSlugs=domain_slugs,
        heroImage=hero_image,
        tldr=tldr,
        intuition=intuition,
        abstractEn=abstract_en,
        abstractZh=abstract_zh,
        background=background,
        backgroundMotivation=extract_labeled_block(background, "动机"),
        backgroundGap=extract_labeled_block(background, "问题缺口"),
        method=method,
        methodOverview=extract_labeled_block(method, "方法概述"),
        methodCore=extract_labeled_block(method, "核心机制"),
        methodBreakdown=extract_bullets(extract_labeled_block(method, "方法拆解")),
        methodTakeaways=extract_bullets(extract_labeled_block(method, "关键要点")),
        results=results,
        resultHighlights=extract_bullets(extract_labeled_block(results, "核心结果")),
        insights=insights,
        insightCore=extract_bullets(extract_labeled_block(insights, "核心 insight")),
        insightRelations=extract_bullets(extract_labeled_block(insights, "和已有方法的关系")),
        insightBorrowable=extract_bullets(extract_labeled_block(insights, "可借鉴点")),
        risks=risks,
        riskLimitations=extract_bullets(extract_labeled_block(risks, "局限")),
        riskScenarios=extract_bullets(extract_labeled_block(risks, "适用场景")),
        riskJudgment=extract_bullets(extract_labeled_block(risks, "最终判断")),
        resultsTableMarkdown=results_table,
        resultsTable=parsed_results_table,
        figureGallery=figures,
        relatedTopicSlugs=related_topics,
    )


def first_nonempty_paragraph(body: str) -> str:
    lines = [line.strip() for line in body.splitlines()]
    bucket: List[str] = []
    for line in lines:
        if not line:
            if bucket:
                break
            continue
        if line.startswith("#"):
            continue
        bucket.append(line)
    return " ".join(bucket).strip()


def extract_related_pages(body: str) -> List[str]:
    matches = re.findall(r"\[\[([^\]]+)\]\]", body)
    values: List[str] = []
    for raw in matches:
        label = raw.split("|", 1)[0].strip()
        if label and label not in values:
            values.append(label)
    return values


def parse_topic_like(path: Path, kind: str) -> ParsedWikiTopic | ParsedWikiSynthesis:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    title = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    title = title or path.stem
    summary = first_nonempty_paragraph(body)
    domain = str(
        frontmatter.get("domain")
        or frontmatter.get("primary_domain_slug")
        or frontmatter.get("primary_domain")
        or ""
    )
    parsed = {
        "slug": resolve_frontmatter_slug(frontmatter, title),
        "title": title,
        "summary": summary,
        "body": body.strip(),
        "tags": frontmatter.get("tags") if isinstance(frontmatter.get("tags"), list) else [],
        "created": str(frontmatter.get("created") or ""),
        "updated": str(frontmatter.get("updated") or ""),
        "sourceTitles": frontmatter.get("sources") if isinstance(frontmatter.get("sources"), list) else [],
        "relatedPages": extract_related_pages(body),
    }
    if kind == "topic":
        return ParsedWikiTopic(domain=slugify(domain) if domain else "", **parsed)
    return ParsedWikiSynthesis(**parsed)


def write_sources(page_root: Path, sources: List[ParsedWikiSource]) -> Path:
    output_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sources.json"
    payload = [asdict(source) for source in sources]
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def write_topic_like(page_root: Path, name: str, values: List[dict[str, Any]]) -> Path:
    output_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{name}.json"
    output_path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def write_detail_json(page_root: Path, bucket: str, slug: str, payload: dict[str, Any]) -> Path:
    output_dir = page_root / "src" / "data" / "generated" / "wiki-sync" / bucket
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slug}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def write_graph_data(page_root: Path, wiki_root: Path) -> Optional[Path]:
    graph_data = wiki_root / "wiki" / "graph-data.json"
    if not graph_data.is_file():
        return None
    output_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "graph-data.json"
    output_path.write_text(graph_data.read_text(encoding="utf-8"), encoding="utf-8")
    return output_path


def build_manifest(wiki_root: Path, page_root: Path) -> SyncManifest:
    return SyncManifest(
        wiki_root=str(wiki_root),
        page_root=str(page_root),
        sources=list_markdown(wiki_root / "wiki" / "sources"),
        topics=list_markdown(wiki_root / "wiki" / "topics"),
        synthesis=list_markdown(wiki_root / "wiki" / "synthesis"),
        graph_assets=list_graph_assets(wiki_root),
    )


def write_manifest(page_root: Path, manifest: SyncManifest) -> Path:
    output_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and stage public wiki content for site sync.")
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="YAML config path")
    common.add_argument("--wiki-root", help="llm-wiki root path")
    common.add_argument("--page-root", help="website repo root path")

    inspect_parser = subparsers.add_parser("inspect", parents=[common], help="Inspect wiki content and print a manifest.")
    inspect_parser.set_defaults(mode="inspect")

    sync_parser = subparsers.add_parser("sync", parents=[common], help="Write a sync manifest into the website repo.")
    sync_parser.set_defaults(mode="sync")

    help_parser = subparsers.add_parser("help", help="Show usage")
    help_parser.set_defaults(mode="help")

    return parser


def command_inspect(args: argparse.Namespace) -> int:
    wiki_root, page_root = resolve_roots(args)
    manifest = build_manifest(wiki_root, page_root)
    print(json.dumps(asdict(manifest), ensure_ascii=False, indent=2))
    return 0


def command_sync(args: argparse.Namespace) -> int:
    wiki_root, page_root = resolve_roots(args)
    manifest = build_manifest(wiki_root, page_root)
    manifest_path = write_manifest(page_root, manifest)
    parsed_sources = [parse_note_source(Path(source)) for source in manifest.sources]
    sources_path = write_sources(page_root, parsed_sources)
    parsed_topics = [parse_topic_like(Path(topic), "topic") for topic in manifest.topics]
    topics_path = write_topic_like(page_root, "topics", [asdict(item) for item in parsed_topics])
    parsed_syntheses = [parse_topic_like(Path(item), "synthesis") for item in manifest.synthesis]
    syntheses_path = write_topic_like(page_root, "synthesis", [asdict(item) for item in parsed_syntheses])
    graph_data_path = write_graph_data(page_root, wiki_root)
    for item in parsed_sources:
      write_detail_json(page_root, "source", item.slug, asdict(item))
    for item in parsed_topics:
      write_detail_json(page_root, "topic", item.slug, asdict(item))
    for item in parsed_syntheses:
      write_detail_json(page_root, "synthesis", item.slug, asdict(item))
    print(f"manifest_path={manifest_path}")
    print(f"sources_path={sources_path}")
    print(f"topics_path={topics_path}")
    print(f"synthesis_path={syntheses_path}")
    if graph_data_path:
      print(f"graph_data_path={graph_data_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        print(HELP_TEXT)
        return 0
    if args.mode == "inspect":
        return command_inspect(args)
    return command_sync(args)


if __name__ == "__main__":
    raise SystemExit(main())
