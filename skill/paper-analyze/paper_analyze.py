#!/usr/bin/env python3
"""
paper_analyze.py - Build final wiki-ready markdown notes for single papers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import re
import sys
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen


HELP_TEXT = """\
paper-analyze: generate a final markdown paper note for llm-wiki.

Usage:
    paper-analyze help
    paper-analyze write --input 2402.12345 --summary "..."
    paper-analyze write --input /path/to/paper.pdf --summary "..."
    paper-analyze write --input https://arxiv.org/abs/1234.5678 --summary "..."
    paper-analyze draft --input https://arxiv.org/pdf/1234.5678.pdf --summary "..."
"""

ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(?P<id>\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
ARXIV_PDF_RE = re.compile(r"arxiv\.org/pdf/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", re.IGNORECASE)
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
ARXIV_FIG_PATH = REPO_ROOT / "skill" / "arxiv-fig" / "arxiv_fig.py"


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - fallback error message
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


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[-\s]+", "-", value, flags=re.UNICODE).strip("-")
    return value or "paper-note"


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_list(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    cleaned: List[str] = []
    for value in values:
        stripped = value.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def ensure_sentence(value: str) -> str:
    value = compact_text(value)
    if not value:
        return value
    if value[-1] in ".!?。！？":
        return value
    return value + "."


@dataclass
class AnalyzeConfig:
    wiki_root: Optional[Path]
    sources_dir: str
    output_mode: str
    draft_dir: Path
    language: str
    r2_base_url: str


@dataclass
class SourceSpec:
    input_value: str
    source_kind: str
    source_url: str
    canonical_url: str
    local_path: Optional[Path]
    paper_id: str
    title_hint: str
    raw_text: str
    abstract_text: str
    publish_date_hint: str


def resolve_config(config_path: Optional[str]) -> AnalyzeConfig:
    payload: Dict[str, Any] = {}
    if config_path:
        path = Path(config_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        payload = load_yaml(path)

    wiki_root_raw = get_nested(payload, "wiki", "root")
    wiki_root = Path(str(wiki_root_raw)).expanduser().resolve() if wiki_root_raw else None
    sources_dir = str(get_nested(payload, "wiki", "sources_dir") or "wiki/sources")
    output_mode = str(get_nested(payload, "paper_analyze", "output_mode") or "write")
    draft_dir_raw = get_nested(payload, "paper_analyze", "draft_dir") or "/tmp/paper-analyze"
    language = str(get_nested(payload, "paper_analyze", "language") or "zh")
    r2_base_url = str(
        get_nested(payload, "paper_analyze", "r2_base_url")
        or get_nested(payload, "rclone", "public_base_url")
        or ""
    ).rstrip("/")

    return AnalyzeConfig(
        wiki_root=wiki_root,
        sources_dir=sources_dir,
        output_mode=output_mode,
        draft_dir=Path(str(draft_dir_raw)).expanduser().resolve(),
        language=language,
        r2_base_url=r2_base_url,
    )


def join_section_lines(values: List[str]) -> str:
    return "\n".join(f"- {ensure_sentence(value)}" for value in values)


def maybe_fetch_url(url: str) -> str:
    request = Request(url, headers={"User-Agent": "followhub-paper-analyze/1.0"})
    with urlopen(request, timeout=20) as response:  # nosec - controlled CLI utility
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def clean_html_text(html_text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title_from_html(html_text: str) -> str:
    match = re.search(r"<title>\s*(.*?)\s*</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    title = re.sub(r"\s*\|\s*arXiv.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*-\s*arXiv.*$", "", title, flags=re.IGNORECASE)
    return title


def extract_meta_content(html_text: str, meta_name: str) -> str:
    pattern = (
        r'<meta[^>]+(?:name|property)=["\']'
        + re.escape(meta_name)
        + r'["\'][^>]+content=["\']([^"\']+)["\']'
    )
    match = re.search(pattern, html_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_arxiv_abstract(html_text: str) -> str:
    meta_abstract = extract_meta_content(html_text, "citation_abstract")
    if meta_abstract:
        return meta_abstract
    match = re.search(
        r'<blockquote[^>]*class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</blockquote>',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    abstract = re.sub(r"<[^>]+>", " ", match.group(1))
    abstract = re.sub(r"^\s*Abstract:\s*", "", abstract, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", abstract).strip()


def split_sentences(text: str) -> List[str]:
    compact = re.sub(r"\s+", " ", text.strip())
    if not compact:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", compact)
    return [part.strip() for part in parts if part.strip()]


def derive_fields_from_text(raw_text: str, abstract_text: str) -> Dict[str, str]:
    abstract_sentences = split_sentences(abstract_text)
    raw_sentences = split_sentences(raw_text)
    usable = abstract_sentences or raw_sentences
    summary = " ".join(usable[:3]) if usable else ""
    research_problem = usable[0] if usable else ""
    core_method = usable[1] if len(usable) > 1 else ""
    if not core_method and len(raw_sentences) > 1:
        core_method = raw_sentences[1]
    return {
        "summary": summary,
        "research_problem": research_problem,
        "core_method": core_method,
    }


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        pages = [doc.load_page(i).get_text("text") for i in range(min(len(doc), 3))]
        return "\n".join(page for page in pages if page).strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return ""


def title_from_path(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip()


def resolve_input_source(input_value: str) -> SourceSpec:
    raw = input_value.strip()
    if not raw:
        raise ValueError("Input source is empty")

    arxiv_id_match = ARXIV_ID_RE.match(raw)
    if arxiv_id_match:
        paper_id = arxiv_id_match.group("id")
        canonical_url = f"https://arxiv.org/abs/{paper_id}"
        html_text = ""
        abstract_text = ""
        title_hint = paper_id
        publish_date_hint = ""
        try:
            html_text = maybe_fetch_url(canonical_url)
            title_hint = extract_title_from_html(html_text) or title_hint
            abstract_text = extract_arxiv_abstract(html_text)
            publish_date_hint = extract_meta_content(html_text, "citation_date")
        except Exception:
            pass
        return SourceSpec(raw, "arxiv_id", canonical_url, canonical_url, None, paper_id, title_hint, clean_html_text(html_text), abstract_text, publish_date_hint)

    candidate_path = Path(raw).expanduser()
    if candidate_path.exists():
        resolved = candidate_path.resolve()
        suffix = resolved.suffix.lower()
        if suffix == ".pdf":
            text = extract_pdf_text(resolved)
            return SourceSpec(raw, "local_pdf", str(resolved), str(resolved), resolved, "", title_from_path(resolved), text, "", "")
        if suffix in {".html", ".htm"}:
            html_text = resolved.read_text(encoding="utf-8", errors="replace")
            title = extract_title_from_html(html_text) or title_from_path(resolved)
            paper_id = ""
            if match := ARXIV_ABS_RE.search(html_text):
                paper_id = match.group("id")
            canonical = f"https://arxiv.org/abs/{paper_id}" if paper_id else str(resolved)
            abstract_text = extract_arxiv_abstract(html_text)
            publish_date_hint = extract_meta_content(html_text, "citation_date")
            return SourceSpec(raw, "local_html", str(resolved), canonical, resolved, paper_id, title, clean_html_text(html_text), abstract_text, publish_date_hint)
        return SourceSpec(raw, "local_file", str(resolved), str(resolved), resolved, "", title_from_path(resolved), "", "", "")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        if match := ARXIV_ABS_RE.search(raw):
            paper_id = match.group("id")
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
            title_hint = paper_id
            html_text = ""
            abstract_text = ""
            publish_date_hint = ""
            try:
                html_text = maybe_fetch_url(canonical_url)
                title_hint = extract_title_from_html(html_text) or title_hint
                abstract_text = extract_arxiv_abstract(html_text)
                publish_date_hint = extract_meta_content(html_text, "citation_date")
            except Exception:
                pass
            return SourceSpec(raw, "arxiv_abs_url", raw, canonical_url, None, paper_id, title_hint, clean_html_text(html_text), abstract_text, publish_date_hint)

        if match := ARXIV_PDF_RE.search(raw):
            paper_id = match.group("id")
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
            title_hint = paper_id
            html_text = ""
            abstract_text = ""
            publish_date_hint = ""
            try:
                html_text = maybe_fetch_url(canonical_url)
                title_hint = extract_title_from_html(html_text) or title_hint
                abstract_text = extract_arxiv_abstract(html_text)
                publish_date_hint = extract_meta_content(html_text, "citation_date")
            except Exception:
                pass
            return SourceSpec(raw, "online_pdf_url", raw, canonical_url, None, paper_id, title_hint, clean_html_text(html_text), abstract_text, publish_date_hint)

        title_hint = title_from_path(Path(parsed.path)) or raw
        html_text = ""
        try:
            html_text = maybe_fetch_url(raw)
        except Exception:
            pass
        return SourceSpec(raw, "web_url", raw, raw, None, "", title_hint, clean_html_text(html_text), "", "")

    raise ValueError(f"Unsupported input source: {raw}")


def maybe_extract_figure_urls(
    source_spec: SourceSpec,
    config_path: Optional[str],
    intent: str,
) -> List[str]:
    if not source_spec.paper_id:
        return []
    if not ARXIV_FIG_PATH.exists():
        return []
    command = [sys.executable, str(ARXIV_FIG_PATH), source_spec.paper_id]
    if intent:
        command.extend(["--intent", intent])
    if config_path:
        command.extend(["--config-file", config_path])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout)
    except Exception:
        return []
    urls: List[str] = []
    for figure in payload.get("figures") or []:
        image_url = (figure.get("image_url") or "").strip()
        if image_url:
            urls.append(image_url)
    return urls


def build_markdown(
    *,
    title: str,
    source_kind: str,
    source_input: str,
    source_url: str,
    publish_date: str,
    domain: str,
    tags: List[str],
    image_urls: List[str],
    related_topics: List[str],
    summary: str,
    research_problem: str,
    core_method: str,
    key_takeaways: List[str],
    experimental_signals: List[str],
    strengths: List[str],
    limitations: List[str],
    critical_notes: List[str],
) -> str:
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    related_yaml = "\n".join(f"  - {topic}" for topic in related_topics)
    images_yaml = "\n".join(f"  - {url}" for url in image_urls)

    figure_lines = "\n".join(f"- ![]({url})" for url in image_urls) if image_urls else "- No figure URLs attached yet."

    return textwrap.dedent(
        f"""\
        ---
        title: "{title}"
        source_type: paper
        source_kind: "{source_kind}"
        source_input: "{source_input}"
        source_url: "{source_url}"
        publish_date: "{publish_date}"
        domain: "{domain}"
        tags:
        {tags_yaml or '  - paper'}
        images:
        {images_yaml or '  []'}
        related_topics:
        {related_yaml or '  []'}
        status: analyzed
        ---

        # {title}

        ## Core Information

        - **Source Kind**: {source_kind}
        - **Source Input**: {source_input}
        - **Source URL**: {source_url or 'N/A'}
        - **Publish Date**: {publish_date}
        - **Domain**: {domain}

        ## Summary

        {ensure_sentence(summary)}

        ## Research Problem

        {ensure_sentence(research_problem)}

        ## Method Overview

        {ensure_sentence(core_method)}

        ## Key Takeaways

        {join_section_lines(key_takeaways) if key_takeaways else '- Not extracted yet.'}

        ## Experimental Signals

        {join_section_lines(experimental_signals) if experimental_signals else '- Not extracted yet.'}

        ## Strengths

        {join_section_lines(strengths) if strengths else '- Not extracted yet.'}

        ## Limitations

        {join_section_lines(limitations) if limitations else '- Not extracted yet.'}

        ## Critical Notes

        {join_section_lines(critical_notes) if critical_notes else '- No additional critical notes yet.'}

        ## Related Topics

        {join_section_lines(related_topics) if related_topics else '- No related topics assigned yet.'}

        ## Figure Notes

        {figure_lines}
        """
    ).strip() + "\n"


def target_output_path(args: argparse.Namespace, config: AnalyzeConfig, slug: str) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()

    mode = args.mode or config.output_mode
    if mode == "draft":
        return config.draft_dir / f"{slug}.md"

    if not config.wiki_root:
        raise RuntimeError("wiki.root is missing in config and no explicit --output was provided")

    return (config.wiki_root / config.sources_dir / f"{slug}.md").resolve()


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate final markdown notes for papers.")
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="YAML config path")
    common.add_argument("--output", help="Explicit markdown output path")
    common.add_argument("--input", required=True, help="Paper input: arXiv id, local PDF, local HTML, arXiv URL, or online PDF URL")
    common.add_argument("--title", help="Paper title override")
    common.add_argument("--source-url", default="", help="Explicit source URL override")
    common.add_argument("--publish-date", default=str(date.today()), help="Paper publish date")
    common.add_argument("--domain", default="llm-vlm", help="Wiki domain slug")
    common.add_argument("--tag", action="append", default=[], help="Repeatable tag")
    common.add_argument("--related-topic", action="append", default=[], help="Repeatable related topic slug")
    common.add_argument("--image-url", action="append", default=[], help="Repeatable public image URL, usually R2")
    common.add_argument("--extract-figures", action="store_true", help="Try to extract figures through arxiv-fig when possible")
    common.add_argument("--figure-intent", default="architecture", help="Intent for figure extraction, used with --extract-figures")
    common.add_argument("--summary", default="", help="Short summary paragraph")
    common.add_argument("--research-problem", default="", help="Research problem paragraph")
    common.add_argument("--core-method", default="", help="Core method paragraph")
    common.add_argument("--key-takeaway", action="append", default=[], help="Repeatable key takeaway")
    common.add_argument("--experimental-signal", action="append", default=[], help="Repeatable experimental signal")
    common.add_argument("--strength", action="append", default=[], help="Repeatable strength")
    common.add_argument("--limitation", action="append", default=[], help="Repeatable limitation")
    common.add_argument("--critical-note", action="append", default=[], help="Repeatable critical note")
    common.add_argument("--print-json", action="store_true", help="Print a machine-readable result object")

    write_parser = subparsers.add_parser("write", parents=[common], help="Write directly into the configured wiki.")
    write_parser.set_defaults(mode="write")

    draft_parser = subparsers.add_parser("draft", parents=[common], help="Write into the configured draft directory.")
    draft_parser.set_defaults(mode="draft")

    help_parser = subparsers.add_parser("help", help="Show usage")
    help_parser.set_defaults(mode="help")

    return parser


def command_write_like(args: argparse.Namespace) -> int:
    config = resolve_config(args.config)
    source_spec = resolve_input_source(args.input)
    title = args.title or source_spec.title_hint
    if not title:
        raise RuntimeError("Unable to derive title from input. Pass --title explicitly.")
    source_url = args.source_url or source_spec.canonical_url or source_spec.source_url
    slug = slugify(title)
    output_path = target_output_path(args, config, slug)

    tags = normalize_list(args.tag) or ["paper", args.domain]
    related_topics = normalize_list(args.related_topic)
    image_urls = normalize_list(args.image_url)
    if args.extract_figures:
        image_urls = image_urls + maybe_extract_figure_urls(source_spec, args.config, args.figure_intent)
        image_urls = normalize_list(image_urls)

    derived = derive_fields_from_text(source_spec.raw_text, source_spec.abstract_text)
    summary = args.summary or derived["summary"]
    if not summary:
        raise RuntimeError("Unable to derive summary from input source. Pass --summary explicitly.")
    publish_date = args.publish_date
    if publish_date == str(date.today()) and source_spec.publish_date_hint:
        publish_date = source_spec.publish_date_hint

    content = build_markdown(
        title=title,
        source_kind=source_spec.source_kind,
        source_input=source_spec.input_value,
        source_url=source_url,
        publish_date=publish_date,
        domain=args.domain,
        tags=tags,
        image_urls=image_urls,
        related_topics=related_topics,
        summary=summary,
        research_problem=args.research_problem or derived["research_problem"] or "Research problem not extracted yet.",
        core_method=args.core_method or derived["core_method"] or "Core method not extracted yet.",
        key_takeaways=normalize_list(args.key_takeaway),
        experimental_signals=normalize_list(args.experimental_signal),
        strengths=normalize_list(args.strength),
        limitations=normalize_list(args.limitation),
        critical_notes=normalize_list(args.critical_note),
    )

    write_note(output_path, content)

    result = {
        "mode": args.mode,
        "title": title,
        "slug": slug,
        "source_kind": source_spec.source_kind,
        "source_url": source_url,
        "paper_id": source_spec.paper_id,
        "output_path": str(output_path),
        "wiki_root": str(config.wiki_root) if config.wiki_root else "",
        "r2_base_url": config.r2_base_url,
    }
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"wrote_markdown={output_path}")
        if config.r2_base_url:
            print(f"r2_base_url={config.r2_base_url}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        print(HELP_TEXT)
        return 0
    return command_write_like(args)


if __name__ == "__main__":
    raise SystemExit(main())
