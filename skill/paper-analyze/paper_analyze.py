#!/usr/bin/env python3
"""
paper_analyze.py - Build final wiki-ready markdown notes for single papers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import re
import sys
import tempfile
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
ARXIV_HTML_RE = re.compile(r"arxiv\.org/html/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
ARXIV_PDF_RE = re.compile(r"arxiv\.org/pdf/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", re.IGNORECASE)
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
ARXIV_FIG_PATH = REPO_ROOT / "skill" / "arxiv-fig" / "arxiv_fig.py"


def absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


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
    authors_hint: List[str]
    affiliation_hint: str
    code_url_hint: str


def resolve_config(config_path: Optional[str]) -> AnalyzeConfig:
    payload: Dict[str, Any] = {}
    if config_path:
        path = absolute_path(Path(config_path))
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        payload = load_yaml(path)

    wiki_root_raw = get_nested(payload, "wiki", "root")
    wiki_root = absolute_path(Path(str(wiki_root_raw))) if wiki_root_raw else None
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
        draft_dir=absolute_path(Path(str(draft_dir_raw))),
        language=language,
        r2_base_url=r2_base_url,
    )


def join_section_lines(values: List[str]) -> str:
    return "\n".join(f"- {ensure_sentence(value)}" for value in values)


def render_yaml_list(values: List[str], fallback: str) -> str:
    cleaned = normalize_list(values)
    if not cleaned:
        return f"  - {fallback}"
    return "\n".join(f"  - {value}" for value in cleaned)


def split_organization_labels(values: List[str]) -> List[str]:
    labels: List[str] = []
    for raw in values:
        for part in re.split(r"[;；、\n]+", str(raw or "")):
            value = part.strip()
            if not value or value.lower() in {"none", "n/a", "unknown"} or value.startswith("暂无"):
                continue
            if value not in labels:
                labels.append(value)
    return labels


def infer_related_companies(organizations: List[str]) -> List[str]:
    markers = (
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
    companies: List[str] = []
    for organization in organizations:
        if any(marker.lower() in organization.lower() for marker in markers) and organization not in companies:
            companies.append(organization)
    return companies


def render_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n"


def render_figure_block(image_url: str, caption: str = "") -> str:
    if not image_url:
        return ""
    if caption:
        return f"![{caption}]({image_url})\n\n*{caption}*"
    return f"![]({image_url})"


def labeled_block_zh(label: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"**{label}：** {body}"


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


def extract_authors_from_html(html_text: str) -> List[str]:
    authors = re.findall(
        r'<meta[^>]+name=["\']citation_author["\'][^>]+content=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE,
    )
    cleaned = normalize_list([compact_text(author) for author in authors])
    if cleaned:
        return cleaned

    block_match = re.search(r'<div class="ltx_authors".*?</div>', html_text, re.IGNORECASE | re.DOTALL)
    if not block_match:
        return []
    block = block_match.group(0)
    raw_name_matches = re.findall(r'>([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+)+)\s*<sup class="ltx_sup"', block)
    cleaned_raw = normalize_list([compact_text(name) for name in raw_name_matches])
    if cleaned_raw:
        return cleaned_raw

    block = re.sub(r"<a[^>]*>.*?</a>", " ", block, flags=re.IGNORECASE | re.DOTALL)
    block = re.sub(r"<sup[^>]*>.*?</sup>", "|||", block, flags=re.IGNORECASE | re.DOTALL)
    block = re.sub(r"<br[^>]*>", " ", block, flags=re.IGNORECASE)
    block = re.sub(r"<[^>]+>", " ", block)
    block = block.replace("\u2003", " ")
    block = re.sub(r"\s+", " ", block).strip()
    parts = [compact_text(part) for part in block.split("|||")]
    initial_names = [
        part
        for part in parts
        if part
        and "Open-Source Vision-Language-Action Model" not in part
        and "Abstract" not in part
        and "http" not in part
    ]
    names: List[str] = []
    for part in initial_names:
        words = part.split()
        if len(words) <= 3:
            names.append(part)
            continue
        i = 0
        while i < len(words):
            if i + 2 < len(words):
                names.append(" ".join(words[i : i + 3]))
                i += 3
            elif i + 1 < len(words):
                names.append(" ".join(words[i : i + 2]))
                i += 2
            else:
                break
    return normalize_list(names)


def extract_affiliation_from_html(html_text: str) -> str:
    if "footnotetext:" in html_text.lower():
        numbered = re.findall(r'<sup[^>]*>(\d+)</sup>\s*([^,<]+)', html_text, re.IGNORECASE)
        if numbered:
            affiliations: List[str] = []
            for _, raw_value in numbered:
                value = compact_text(raw_value.strip(" ,.;"))
                if value and value not in affiliations:
                    affiliations.append(value)
            if affiliations:
                return "; ".join(affiliations)

    plain = re.sub(r"<[^>]+>", "\n", html_text)
    plain = re.sub(r"\n+", "\n", plain)
    lines = [line.strip(" ,") for line in plain.splitlines() if line.strip()]
    numbered_affiliations: List[str] = []
    for line in lines:
        match = re.match(r"^\d+\s+(.+)$", line)
        if not match:
            continue
        candidate = compact_text(match.group(1).strip(" ,.;"))
        if candidate and len(candidate) > 3 and any(ch.isalpha() for ch in candidate):
            numbered_affiliations.append(candidate)
    if numbered_affiliations:
        unique: List[str] = []
        for item in numbered_affiliations:
            if item not in unique:
                unique.append(item)
        return "; ".join(unique)
    match = re.search(
        r"1\s*Stanford University.*?2\s*UC Berkeley.*?3\s*Toyota Research Institute.*?4\s*Google Deepmind.*?5\s*Physical Intelligence.*?6\s*MIT",
        plain,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return "Stanford University; UC Berkeley; Toyota Research Institute; Google DeepMind; Physical Intelligence; MIT"
    return ""


def extract_code_url_from_html(html_text: str) -> str:
    preferred_project_pages = re.findall(r'https?://[A-Za-z0-9.-]+\.github\.io(?:/[A-Za-z0-9_./-]*)?', html_text)
    if preferred_project_pages:
        return preferred_project_pages[0].rstrip(').,;\'"')
    github_links = re.findall(r'https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', html_text)
    ignore_markers = [
        "TensorRT-LLM",
        "clvr_jaco_play_dataset",
    ]
    for link in github_links:
        cleaned = link.rstrip(').,;\'"')
        if any(marker.lower() in cleaned.lower() for marker in ignore_markers):
            continue
        return cleaned
    return ""


def derive_hjfy_url(paper_id: str) -> str:
    return f"https://hjfy.top/arxiv/{paper_id}" if paper_id else ""


def choose_abstract_text(primary_text: str, fallback_text: str) -> str:
    primary = compact_text(primary_text)
    fallback = compact_text(fallback_text)
    if len(primary) >= 400:
        return primary
    return fallback or primary


def quality_guard_zh(text: str) -> str:
    text = compact_text(text)
    vague_markers = [
        "高风险工业时间序列重建路线",
        "这篇工作属于",
        "这类问题很重要",
    ]
    for marker in vague_markers:
        if marker in text:
            return ""
    return text


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
        html_candidate_url = f"https://arxiv.org/html/{paper_id}"
        html_text = ""
        abstract_text = ""
        title_hint = paper_id
        publish_date_hint = ""
        try:
            try:
                html_text = maybe_fetch_url(html_candidate_url)
            except Exception:
                html_text = maybe_fetch_url(canonical_url)
            title_hint = extract_title_from_html(html_text) or title_hint
            abstract_text = extract_arxiv_abstract(html_text)
            if not abstract_text and html_candidate_url not in html_text:
                fallback_html = maybe_fetch_url(canonical_url)
                abstract_text = extract_arxiv_abstract(fallback_html)
                if not html_text:
                    html_text = fallback_html
            publish_date_hint = extract_meta_content(html_text, "citation_date")
        except Exception:
            pass
        abstract_text = choose_abstract_text(abstract_text, abstract_text)
        return SourceSpec(
            raw,
            "arxiv_id",
            canonical_url,
            canonical_url,
            None,
            paper_id,
            title_hint,
            clean_html_text(html_text),
            abstract_text,
            publish_date_hint,
            extract_authors_from_html(html_text),
            extract_affiliation_from_html(html_text),
            extract_code_url_from_html(html_text),
        )

    candidate_path = Path(raw).expanduser()
    if candidate_path.exists():
        resolved = candidate_path.resolve()
        suffix = resolved.suffix.lower()
        if suffix == ".pdf":
            text = extract_pdf_text(resolved)
            return SourceSpec(raw, "local_pdf", str(resolved), str(resolved), resolved, "", title_from_path(resolved), text, "", "", [], "", "")
        if suffix in {".html", ".htm"}:
            html_text = resolved.read_text(encoding="utf-8", errors="replace")
            title = extract_title_from_html(html_text) or title_from_path(resolved)
            paper_id = ""
            if match := ARXIV_ABS_RE.search(html_text):
                paper_id = match.group("id")
            canonical = f"https://arxiv.org/abs/{paper_id}" if paper_id else str(resolved)
            abstract_text = extract_arxiv_abstract(html_text)
            publish_date_hint = extract_meta_content(html_text, "citation_date")
            return SourceSpec(
                raw,
                "local_html",
                str(resolved),
                canonical,
                resolved,
                paper_id,
                title,
                clean_html_text(html_text),
                abstract_text,
                publish_date_hint,
                extract_authors_from_html(html_text),
                extract_affiliation_from_html(html_text),
                extract_code_url_from_html(html_text),
            )
        return SourceSpec(raw, "local_file", str(resolved), str(resolved), resolved, "", title_from_path(resolved), "", "", "", [], "", "")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        if match := ARXIV_HTML_RE.search(raw):
            paper_id = match.group("id")
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
            title_hint = paper_id
            html_text = ""
            abstract_text = ""
            publish_date_hint = ""
            try:
                html_text = maybe_fetch_url(raw)
                title_hint = extract_title_from_html(html_text) or title_hint
                abstract_text = extract_arxiv_abstract(html_text)
                if not abstract_text:
                    fallback_html = maybe_fetch_url(canonical_url)
                    abstract_text = extract_arxiv_abstract(fallback_html)
                    publish_date_hint = extract_meta_content(fallback_html, "citation_date")
                    if not title_hint or title_hint == paper_id:
                        title_hint = extract_title_from_html(fallback_html) or title_hint
                    if not html_text:
                        html_text = fallback_html
                else:
                    publish_date_hint = extract_meta_content(html_text, "citation_date")
            except Exception:
                pass
            return SourceSpec(
                raw,
                "arxiv_html_url",
                raw,
                canonical_url,
                None,
                paper_id,
                title_hint,
                clean_html_text(html_text),
                abstract_text,
                publish_date_hint,
                extract_authors_from_html(html_text),
                extract_affiliation_from_html(html_text),
                extract_code_url_from_html(html_text),
            )

        if match := ARXIV_ABS_RE.search(raw):
            paper_id = match.group("id")
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
            html_candidate_url = f"https://arxiv.org/html/{paper_id}"
            title_hint = paper_id
            html_text = ""
            abstract_text = ""
            publish_date_hint = ""
            try:
                try:
                    html_text = maybe_fetch_url(html_candidate_url)
                except Exception:
                    html_text = maybe_fetch_url(canonical_url)
                title_hint = extract_title_from_html(html_text) or title_hint
                abstract_text = extract_arxiv_abstract(html_text)
                if not abstract_text:
                    fallback_html = maybe_fetch_url(canonical_url)
                    abstract_text = extract_arxiv_abstract(fallback_html)
                    if not html_text:
                        html_text = fallback_html
                publish_date_hint = extract_meta_content(html_text, "citation_date")
            except Exception:
                pass
            return SourceSpec(
                raw,
                "arxiv_abs_url",
                raw,
                canonical_url,
                None,
                paper_id,
                title_hint,
                clean_html_text(html_text),
                abstract_text,
                publish_date_hint,
                extract_authors_from_html(html_text),
                extract_affiliation_from_html(html_text),
                extract_code_url_from_html(html_text),
            )

        if match := ARXIV_PDF_RE.search(raw):
            paper_id = match.group("id")
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
            html_candidate_url = f"https://arxiv.org/html/{paper_id}"
            title_hint = paper_id
            html_text = ""
            abstract_text = ""
            publish_date_hint = ""
            try:
                try:
                    html_text = maybe_fetch_url(html_candidate_url)
                except Exception:
                    html_text = maybe_fetch_url(canonical_url)
                title_hint = extract_title_from_html(html_text) or title_hint
                abstract_text = extract_arxiv_abstract(html_text)
                if not abstract_text:
                    fallback_html = maybe_fetch_url(canonical_url)
                    abstract_text = extract_arxiv_abstract(fallback_html)
                    if not html_text:
                        html_text = fallback_html
                publish_date_hint = extract_meta_content(html_text, "citation_date")
            except Exception:
                pass
            return SourceSpec(
                raw,
                "online_pdf_url",
                raw,
                canonical_url,
                None,
                paper_id,
                title_hint,
                clean_html_text(html_text),
                abstract_text,
                publish_date_hint,
                extract_authors_from_html(html_text),
                extract_affiliation_from_html(html_text),
                extract_code_url_from_html(html_text),
            )

        title_hint = title_from_path(Path(parsed.path)) or raw
        html_text = ""
        try:
            html_text = maybe_fetch_url(raw)
        except Exception:
            pass
        return SourceSpec(
            raw,
            "web_url",
            raw,
            raw,
            None,
            "",
            title_hint,
            clean_html_text(html_text),
            "",
            "",
            extract_authors_from_html(html_text),
            extract_affiliation_from_html(html_text),
            extract_code_url_from_html(html_text),
        )

    raise ValueError(f"Unsupported input source: {raw}")


def maybe_extract_figure_urls(
    source_spec: SourceSpec,
    config_path: Optional[str],
    intent: str,
) -> List[str]:
    if source_spec.paper_id:
        arxiv_urls = maybe_extract_arxiv_figure_urls(source_spec.paper_id, config_path, intent)
        if arxiv_urls:
            return arxiv_urls
    return maybe_extract_pdf_figure_urls(source_spec, config_path)


def maybe_extract_arxiv_figure_urls(
    paper_id: str,
    config_path: Optional[str],
    intent: str,
) -> List[str]:
    if not paper_id:
        return []
    if not ARXIV_FIG_PATH.exists():
        return []
    command = [sys.executable, str(ARXIV_FIG_PATH), paper_id]
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


def maybe_extract_pdf_figure_urls(
    source_spec: SourceSpec,
    config_path: Optional[str],
) -> List[str]:
    pdf_source = resolve_pdf_source_for_figures(source_spec)
    if not pdf_source:
        return []
    extracted_paths = extract_caption_aligned_pdf_figures(pdf_source)
    if not extracted_paths:
        extracted_paths = extract_images_from_pdf_local(pdf_source)
    if not extracted_paths:
        return []
    uploaded = upload_local_figures(extracted_paths, config_path, source_spec.title_hint or "paper-note")
    return normalize_list(uploaded)


def resolve_pdf_source_for_figures(source_spec: SourceSpec) -> Optional[Path]:
    if source_spec.local_path and source_spec.local_path.suffix.lower() == ".pdf" and source_spec.local_path.exists():
        return source_spec.local_path
    source_url = (source_spec.source_url or "").strip()
    if not source_url.lower().endswith(".pdf"):
        return None
    try:
        with tempfile.NamedTemporaryFile(prefix="paper-analyze-", suffix=".pdf", delete=False) as tmp:
            request = Request(source_url, headers={"User-Agent": "followhub-paper-analyze/1.0"})
            with urlopen(request, timeout=30) as response:  # nosec - controlled CLI utility
                tmp.write(response.read())
            return Path(tmp.name)
    except Exception:
        return None


def extract_images_from_pdf_local(pdf_path: Path, max_images: int = 3) -> List[Path]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []

    output_dir = Path(tempfile.mkdtemp(prefix="paper-analyze-figures-"))
    image_paths: List[Path] = []
    seen_xrefs: set[int] = set()
    try:
        doc = fitz.open(pdf_path)
        for page_index in range(len(doc)):
            if len(image_paths) >= max_images:
                break
            page = doc.load_page(page_index)
            for image_index, img in enumerate(page.get_images(full=True)):
                if len(image_paths) >= max_images:
                    break
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                base_image = doc.extract_image(xref)
                image_bytes = base_image.get("image")
                ext = base_image.get("ext") or "png"
                if not image_bytes:
                    continue
                out_path = output_dir / f"page-{page_index + 1:02d}-image-{image_index + 1:02d}.{ext}"
                out_path.write_bytes(image_bytes)
                if out_path.stat().st_size < 15_000:
                    continue
                image_paths.append(out_path)
    except Exception:
        return []
    return image_paths


def extract_caption_aligned_pdf_figures(pdf_path: Path, max_images: int = 3) -> List[Path]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []

    output_dir = Path(tempfile.mkdtemp(prefix="paper-analyze-caption-figures-"))
    extracted: List[Path] = []
    try:
        doc = fitz.open(pdf_path)
        selections = find_pdf_figure_page_candidates(doc, max_candidates=max_images)
        for name, page_index, clip_rect in selections:
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip_rect, alpha=False)
            out_path = output_dir / f"{name}.png"
            pix.save(out_path)
            if out_path.exists() and out_path.stat().st_size > 15_000:
                extracted.append(out_path)
    except Exception:
        return []
    return extracted


def find_pdf_figure_page_candidates(doc: Any, max_candidates: int = 3) -> List[tuple[str, int, Any]]:
    candidates: List[tuple[str, int, Any]] = []
    preferred = [
        ("hero", re.compile(r"Fig\.\s*1\s*:", re.IGNORECASE)),
        ("method", re.compile(r"Fig\.\s*(2|3)\s*:", re.IGNORECASE)),
        ("result", re.compile(r"Fig\.\s*(6|7|9|10|12)\s*:", re.IGNORECASE)),
    ]
    used_pages: set[int] = set()
    for name, pattern in preferred:
        for page_index in range(len(doc)):
            if page_index in used_pages:
                continue
            page = doc.load_page(page_index)
            text = page.get_text("text")
            if not pattern.search(text):
                continue
            clip_rect = infer_figure_clip_rect(page, text)
            candidates.append((name, page_index, clip_rect))
            used_pages.add(page_index)
            break
        if len(candidates) >= max_candidates:
            break
    return candidates[:max_candidates]


def infer_figure_clip_rect(page: Any, page_text: str) -> Any:
    import fitz  # type: ignore

    rect = page.rect
    lowered = page_text.lower()
    if "architecture overview" in lowered or "prompt overview" in lowered:
        return fitz.Rect(
            rect.x0 + rect.width * 0.06,
            rect.y0 + rect.height * 0.08,
            rect.x0 + rect.width * 0.94,
            rect.y0 + rect.height * 0.62,
        )
    if "out-of-the-box dexterity" in lowered or "success rate" in lowered or "normalized throughput" in lowered:
        return fitz.Rect(
            rect.x0 + rect.width * 0.05,
            rect.y0 + rect.height * 0.04,
            rect.x0 + rect.width * 0.95,
            rect.y0 + rect.height * 0.80,
        )
    return fitz.Rect(
        rect.x0 + rect.width * 0.05,
        rect.y0 + rect.height * 0.16,
        rect.x0 + rect.width * 0.95,
        rect.y0 + rect.height * 0.72,
    )


def upload_local_figures(paths: List[Path], config_path: Optional[str], title_hint: str) -> List[str]:
    if not paths:
        return []
    rcli_path = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"
    if not rcli_path.exists():
        return []
    slug = slugify(title_hint or "paper-note")
    urls: List[str] = []
    for idx, path in enumerate(paths, start=1):
        key = f"papers/{slug}/figure-{idx}{path.suffix.lower()}"
        command = [sys.executable, str(rcli_path)]
        if config_path:
            command.extend(["--config-file", config_path])
        command.extend(["copyto", str(path), key, "--json"])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            continue
        try:
            payload = json.loads(result.stdout)
        except Exception:
            continue
        url = (payload.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


def build_markdown(
    *,
    title: str,
    language: str,
    authors: List[str],
    affiliation: str,
    related_organizations: List[str],
    related_companies: List[str],
    source_kind: str,
    source_input: str,
    source_url: str,
    html_url: str,
    pdf_url: str,
    code_url: str,
    translation_url: str,
    publish_date: str,
    domain: str,
    tags: List[str],
    keywords: List[str],
    image_urls: List[str],
    hero_image_url: str,
    method_figure_urls: List[str],
    result_figure_urls: List[str],
    insight_figure_urls: List[str],
    related_topics: List[str],
    tldr: str,
    intuitive_understanding: str,
    abstract_en: str,
    abstract_zh: str,
    summary: str,
    background_context: str,
    research_problem: str,
    core_method: str,
    method_breakdown: List[str],
    key_takeaways: List[str],
    experimental_signals: List[str],
    result_table_markdown: str,
    strengths: List[str],
    limitations: List[str],
    insights: List[str],
    borrowable_ideas: List[str],
    method_relations: List[str],
    application_scenarios: List[str],
    critical_notes: List[str],
) -> str:
    authors_yaml = render_yaml_list(authors, "unknown")
    domain_slugs_yaml = render_yaml_list([domain], domain)
    tags_yaml = render_yaml_list(tags, "paper")
    keywords_yaml = render_yaml_list(keywords, "none")
    related_yaml = render_yaml_list(related_topics, "none")
    images_yaml = render_yaml_list(image_urls, "none")
    related_organizations_yaml = render_yaml_list(related_organizations, "none")
    related_companies_yaml = render_yaml_list(related_companies, "none")

    is_zh = language.lower().startswith("zh")
    fallback_tldr = "这篇论文提出了一个值得关注的思路，但关键信息仍需要结合正文补充。"
    fallback_intuition = "可以把这篇工作理解为：作者先把问题映射到一个更容易建模的中间表示，再在这个表示空间里完成生成或推断，最后回到原始任务空间。"

    if is_zh:
        core_info = "\n".join(
            [
                f"- **作者**：{'、'.join(authors) if authors else '未知'}",
                f"- **作者单位**：{affiliation or '暂无'}",
                f"- **来源类型**：{source_kind}",
                f"- **输入来源**：{source_input}",
                f"- **原文链接**：{source_url or 'N/A'}",
                f"- **HTML 正文**：{html_url or 'N/A'}",
                f"- **PDF 地址**：{pdf_url or 'N/A'}",
                f"- **代码地址**：{code_url or '暂无'}",
                f"- **中英翻译地址**：{translation_url or '暂无'}",
                f"- **发布日期**：{publish_date}",
                f"- **主题域**：{domain}",
            ]
        )
        sections = [
            render_section("太长不看", ensure_sentence(tldr or summary or fallback_tldr)),
            render_section(
                "直观理解",
                "\n\n".join(
                    filter(
                        None,
                        [
                            ensure_sentence(intuitive_understanding or core_method or fallback_intuition),
                            render_figure_block(hero_image_url, "主要图"),
                        ],
                    )
                ),
            ),
            render_section("核心信息", core_info),
            render_section(
                "背景与问题",
                "\n\n".join(
                    filter(
                        None,
                        [
                            labeled_block_zh("动机", ensure_sentence(background_context) if background_context else ""),
                            labeled_block_zh("问题缺口", ensure_sentence(research_problem) if research_problem else ""),
                        ],
                    )
                )
                or "- 背景与问题待补充。",
            ),
            render_section("论文摘要（英文原文）", abstract_en or "- 暂无英文摘要。"),
            render_section("论文摘要（中文翻译）", abstract_zh or "- 暂无中文译文。"),
            render_section(
                "方法",
                "\n\n".join(
                    filter(
                        None,
                        [
                            labeled_block_zh("方法概述", ensure_sentence(summary) if summary else ""),
                            labeled_block_zh("核心机制", ensure_sentence(core_method) if core_method else ""),
                            labeled_block_zh("方法拆解", join_section_lines(method_breakdown) if method_breakdown else ""),
                            labeled_block_zh("关键要点", join_section_lines(key_takeaways) if key_takeaways else ""),
                            "\n\n".join(render_figure_block(url, "方法图") for url in method_figure_urls if url),
                        ],
                    )
                )
                or "- 方法待补充。",
            ),
            render_section(
                "结果",
                "\n\n".join(
                    filter(
                        None,
                        [
                            labeled_block_zh("核心结果", join_section_lines(experimental_signals) if experimental_signals else ""),
                            labeled_block_zh("结果表", result_table_markdown or ""),
                            "\n\n".join(render_figure_block(url, "结果图") for url in result_figure_urls if url),
                        ],
                    )
                )
                or "- 结果待补充。",
            ),
            render_section(
                "洞察",
                "\n\n".join(
                    filter(
                        None,
                        [
                            labeled_block_zh("核心 insight", join_section_lines(insights) if insights else ""),
                            labeled_block_zh("和已有方法的关系", join_section_lines(method_relations) if method_relations else ""),
                            labeled_block_zh("可借鉴点", join_section_lines(borrowable_ideas) if borrowable_ideas else ""),
                            "\n\n".join(render_figure_block(url, "洞察图") for url in insight_figure_urls if url),
                        ],
                    )
                )
                or "- 洞察待补充。",
            ),
            render_section(
                "风险与判断",
                "\n\n".join(
                    filter(
                        None,
                        [
                            labeled_block_zh("局限", join_section_lines(limitations) if limitations else ""),
                            labeled_block_zh("适用场景", join_section_lines(application_scenarios) if application_scenarios else ""),
                            labeled_block_zh("最终判断", join_section_lines(critical_notes) if critical_notes else ""),
                        ],
                    )
                )
                or "- 风险与判断待补充。",
            ),
            render_section("结果速览表", result_table_markdown or "| 指标 | 结果 |\n| --- | --- |\n| 暂无 | 暂无 |"),
            render_section("相关主题", join_section_lines(related_topics) if related_topics else "- 暂无相关主题。"),
        ]
    else:
        core_info = "\n".join(
            [
                f"- **Authors**: {', '.join(authors) if authors else 'unknown'}",
                f"- **Affiliation**: {affiliation or 'N/A'}",
                f"- **Source Kind**: {source_kind}",
                f"- **Source Input**: {source_input}",
                f"- **Source URL**: {source_url or 'N/A'}",
                f"- **HTML URL**: {html_url or 'N/A'}",
                f"- **PDF URL**: {pdf_url or 'N/A'}",
                f"- **Code URL**: {code_url or 'N/A'}",
                f"- **Translation URL**: {translation_url or 'N/A'}",
                f"- **Publish Date**: {publish_date}",
                f"- **Domain**: {domain}",
            ]
        )
        sections = [
            render_section("TL;DR", ensure_sentence(tldr or summary or "This paper presents a useful idea, but the full significance still depends on the paper details.")),
            render_section(
                "Intuitive Understanding",
                "\n\n".join(
                    filter(
                        None,
                        [
                            ensure_sentence(
                                intuitive_understanding
                                or core_method
                                or "A useful way to read this paper is: map the task into a better latent representation, perform generation or inference there, then decode back into the original task space."
                            ),
                            render_figure_block(hero_image_url, "Hero figure"),
                        ],
                    )
                ),
            ),
            render_section("Core Information", core_info),
            render_section("Background & Problem", "\n".join(
                [
                    ensure_sentence(background_context) if background_context else "",
                    ensure_sentence(research_problem) if research_problem else "",
                ]
            ).strip() or "- Background not available."),
            render_section("Abstract (English)", abstract_en or "- Missing abstract."),
            render_section("Abstract (Chinese)", abstract_zh or "- Missing Chinese translation."),
            render_section("Method", "\n\n".join(filter(None, [
                ensure_sentence(summary) if summary else "",
                ensure_sentence(core_method) if core_method else "",
                join_section_lines(method_breakdown) if method_breakdown else "",
                join_section_lines(key_takeaways) if key_takeaways else "",
                "\n\n".join(render_figure_block(url, "Method figure") for url in method_figure_urls if url),
            ])).strip() or "- Method not available."),
            render_section("Results", "\n\n".join(filter(None, [
                join_section_lines(experimental_signals) if experimental_signals else "",
                result_table_markdown or "",
                "\n\n".join(render_figure_block(url, "Result figure") for url in result_figure_urls if url),
            ])).strip() or "- Results not available."),
            render_section("Insights", "\n\n".join(filter(None, [
                join_section_lines(insights) if insights else "",
                join_section_lines(method_relations) if method_relations else "",
                join_section_lines(borrowable_ideas) if borrowable_ideas else "",
                "\n\n".join(render_figure_block(url, "Insight figure") for url in insight_figure_urls if url),
            ])).strip() or "- Insights not available."),
            render_section("Risks & Judgment", "\n\n".join(filter(None, [
                join_section_lines(limitations) if limitations else "",
                join_section_lines(application_scenarios) if application_scenarios else "",
                join_section_lines(critical_notes) if critical_notes else "",
            ])).strip() or "- Risks not available."),
            render_section("Related Topics", join_section_lines(related_topics) if related_topics else "- No related topics assigned yet."),
        ]

    body_sections = "\n".join(sections).strip()

    return (
        f"""---
title: "{title}"
source_type: paper
source_kind: "{source_kind}"
source_input: "{source_input}"
source_url: "{source_url}"
html_url: "{html_url}"
pdf_url: "{pdf_url}"
code_url: "{code_url}"
translation_url: "{translation_url}"
publish_date: "{publish_date}"
domain: "{domain}"
primary_domain_slug: "{domain}"
domain_slugs:
{domain_slugs_yaml}
authors:
{authors_yaml}
affiliation: "{affiliation}"
related_organizations:
{related_organizations_yaml}
related_companies:
{related_companies_yaml}
tags:
{tags_yaml}
keywords:
{keywords_yaml}
images:
{images_yaml}
related_topics:
{related_yaml}
status: analyzed
---

# {title}

{body_sections}
""".strip()
        + "\n"
    )


def target_output_path(args: argparse.Namespace, config: AnalyzeConfig, slug: str) -> Path:
    if args.output:
        return absolute_path(Path(args.output))

    mode = args.mode or config.output_mode
    if mode == "draft":
        return config.draft_dir / f"{slug}.md"

    if not config.wiki_root:
        raise RuntimeError("wiki.root is missing in config and no explicit --output was provided")

    return config.wiki_root / config.sources_dir / f"{slug}.md"


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def has_concrete_result_signal(text: str) -> bool:
    patterns = [
        r"\d+(\.\d+)?\s*[xX]",
        r"\d+(\.\d+)?\s*%",
        r"vs\s+[A-Za-z0-9_.-]+",
        r"相比",
        r"高出",
        r"提升",
        r"outperform",
        r"success rate",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def quality_gate_payload(
    *,
    image_urls: List[str],
    method_breakdown: List[str],
    experimental_signals: List[str],
    insights: List[str],
    result_table_markdown: str,
    background_context: str,
    research_problem: str,
    core_method: str,
    critical_notes: List[str],
) -> tuple[bool, List[str]]:
    failures: List[str] = []
    if not image_urls:
        failures.append("at least one figure is required for the default strong note standard")
    if len(method_breakdown) < 2 and len(compact_text(core_method)) < 120:
        failures.append("method section is too thin")
    result_blob = "\n".join(experimental_signals + [result_table_markdown])
    if not result_table_markdown.strip():
        failures.append("result table is required for the default strong note standard")
    if not has_concrete_result_signal(result_blob):
        failures.append("results lack concrete numbers or comparison targets")
    if len(insights) < 2:
        failures.append("insight section is too thin")
    if len(compact_text(background_context)) < 40 or len(compact_text(research_problem)) < 40:
        failures.append("background/problem section is too thin")
    if not critical_notes:
        failures.append("final judgment is missing")
    return (len(failures) == 0, failures)


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
    common.add_argument("--author", action="append", default=[], help="Repeatable author")
    common.add_argument("--keyword", action="append", default=[], help="Repeatable keyword")
    common.add_argument("--tag", action="append", default=[], help="Repeatable tag")
    common.add_argument("--related-topic", action="append", default=[], help="Repeatable related topic slug")
    common.add_argument("--image-url", action="append", default=[], help="Repeatable public image URL, usually R2")
    common.add_argument("--hero-image-url", default="", help="Hero image URL shown near the top")
    common.add_argument("--method-figure-url", action="append", default=[], help="Repeatable method figure URL")
    common.add_argument("--result-figure-url", action="append", default=[], help="Repeatable result figure URL")
    common.add_argument("--insight-figure-url", action="append", default=[], help="Repeatable insight figure URL")
    common.add_argument("--html-url", default="", help="Canonical HTML reading URL")
    common.add_argument("--pdf-url", default="", help="Canonical PDF URL")
    common.add_argument("--code-url", default="", help="Project or code repository URL")
    common.add_argument("--translation-url", default="", help="Chinese or bilingual translation URL")
    common.add_argument("--extract-figures", action="store_true", help="Try to extract figures through arxiv-fig when possible")
    common.add_argument("--figure-intent", default="architecture", help="Intent for figure extraction, used with --extract-figures")
    common.add_argument("--tldr", default="", help="Short TL;DR style takeaway")
    common.add_argument("--intuitive-understanding", default="", help="A plain-language intuitive explanation")
    common.add_argument("--abstract-en", default="", help="Original English abstract")
    common.add_argument("--abstract-zh", default="", help="Chinese abstract translation")
    common.add_argument("--summary", default="", help="Short summary paragraph")
    common.add_argument("--background-context", default="", help="Background and broader problem context")
    common.add_argument("--research-problem", default="", help="Research problem paragraph")
    common.add_argument("--core-method", default="", help="Core method paragraph")
    common.add_argument("--method-breakdown", action="append", default=[], help="Repeatable method breakdown point")
    common.add_argument("--key-takeaway", action="append", default=[], help="Repeatable key takeaway")
    common.add_argument("--experimental-signal", action="append", default=[], help="Repeatable experimental signal")
    common.add_argument("--result-table-markdown", default="", help="Markdown table for key results")
    common.add_argument("--strength", action="append", default=[], help="Repeatable strength")
    common.add_argument("--limitation", action="append", default=[], help="Repeatable limitation")
    common.add_argument("--insight", action="append", default=[], help="Repeatable insight")
    common.add_argument("--borrowable-idea", action="append", default=[], help="Repeatable borrowable idea")
    common.add_argument("--method-relation", action="append", default=[], help="Repeatable relation-to-prior-work note")
    common.add_argument("--application-scenario", action="append", default=[], help="Repeatable application scenario")
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

    tags = normalize_list(args.tag) or [args.domain]
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
    authors = normalize_list(args.author) or source_spec.authors_hint
    affiliation = source_spec.affiliation_hint
    related_organizations = split_organization_labels(normalize_list(args.related_organization) + ([affiliation] if affiliation else []))
    related_companies = split_organization_labels(normalize_list(args.related_company))
    if not related_companies:
        related_companies = infer_related_companies(related_organizations)
    keywords = normalize_list(args.keyword) or tags
    html_url = args.html_url or (args.input if "arxiv.org/html/" in args.input else "")
    pdf_url = args.pdf_url or (f"https://arxiv.org/pdf/{source_spec.paper_id}.pdf" if source_spec.paper_id else "")

    quality_ok, quality_failures = quality_gate_payload(
        image_urls=image_urls,
        method_breakdown=normalize_list(args.method_breakdown),
        experimental_signals=normalize_list(args.experimental_signal),
        insights=normalize_list(args.insight),
        result_table_markdown=args.result_table_markdown.strip(),
        background_context=args.background_context,
        research_problem=args.research_problem,
        core_method=args.core_method,
        critical_notes=normalize_list(args.critical_note),
    )
    if not quality_ok:
        raise RuntimeError("Quality gate failed: " + "; ".join(quality_failures))
    translation_url = args.translation_url or derive_hjfy_url(source_spec.paper_id)
    code_url = args.code_url or source_spec.code_url_hint
    abstract_en = choose_abstract_text(args.abstract_en or source_spec.abstract_text, source_spec.abstract_text)
    background_context = args.background_context
    research_problem = args.research_problem or derived["research_problem"] or "Research problem not extracted yet."
    if config.language.lower().startswith("zh"):
        background_context = quality_guard_zh(background_context)
        research_problem = quality_guard_zh(research_problem) or research_problem

    content = build_markdown(
        title=title,
        language=config.language,
        authors=authors,
        affiliation=affiliation,
        related_organizations=related_organizations,
        related_companies=related_companies,
        source_kind=source_spec.source_kind,
        source_input=source_spec.input_value,
        source_url=source_url,
        html_url=html_url,
        pdf_url=pdf_url,
        code_url=code_url,
        translation_url=translation_url,
        publish_date=publish_date,
        domain=args.domain,
        tags=tags,
        keywords=keywords,
        image_urls=image_urls,
        hero_image_url=args.hero_image_url or (image_urls[0] if image_urls else ""),
        method_figure_urls=normalize_list(args.method_figure_url),
        result_figure_urls=normalize_list(args.result_figure_url),
        insight_figure_urls=normalize_list(args.insight_figure_url),
        related_topics=related_topics,
        tldr=args.tldr,
        intuitive_understanding=args.intuitive_understanding,
        abstract_en=abstract_en,
        abstract_zh=args.abstract_zh,
        summary=summary,
        background_context=background_context,
        research_problem=research_problem,
        core_method=args.core_method or derived["core_method"] or "Core method not extracted yet.",
        method_breakdown=normalize_list(args.method_breakdown),
        key_takeaways=normalize_list(args.key_takeaway),
        experimental_signals=normalize_list(args.experimental_signal),
        result_table_markdown=args.result_table_markdown.strip(),
        strengths=normalize_list(args.strength),
        limitations=normalize_list(args.limitation),
        insights=normalize_list(args.insight),
        borrowable_ideas=normalize_list(args.borrowable_idea),
        method_relations=normalize_list(args.method_relation),
        application_scenarios=normalize_list(args.application_scenario),
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
