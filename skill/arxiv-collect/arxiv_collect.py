#!/usr/bin/env python3
"""
arxiv_collect.py - Raw arXiv acquisition for daily and backfill workflows.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import time
import re
import socket
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None


LIST_URL_TEMPLATE = "https://arxiv.org/list/{category}/new?skip=0&show=2000"
ABS_URL_TEMPLATE = "https://arxiv.org/abs/{arxiv_id}"
API_URL = "https://export.arxiv.org/api/query"
LIST_FETCH_MAX_WORKERS = 4
ABS_FETCH_MAX_WORKERS = 8
API_FETCH_MAX_WORKERS = 1
API_PAGE_SIZE = 100
API_ID_LIST_CHUNK_SIZE = 25
API_REQUEST_DELAY_SECONDS = 5
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
STOPWORDS = {
    "about",
    "after",
    "before",
    "between",
    "data",
    "focuses",
    "recent",
    "robot",
    "robots",
    "their",
    "using",
    "with",
    "work",
}
HELP_TEXT = """\
arxiv-collect: Raw arXiv acquisition for daily briefs, backfills, and search.

Usage:
    arxiv-collect help
    arxiv-collect validate-profile --profile /path/to/followhub.yaml
    arxiv-collect run --mode daily --profile /path/to/followhub.yaml
    arxiv-collect run --mode backfill --profile /path/to/followhub.yaml --from-date YYYY-MM-DD --to-date YYYY-MM-DD

Modes:
    daily     Prefer arXiv list/new pages and keep only New submissions.
    backfill  Use one submittedDate API window per day and keep each day separate.
    search    Use API query mode with pagination and shared profile filters.
"""
_ENRICH_MODULE = None


@dataclass
class DailySettings:
    new_submissions_only: bool = True
    max_results_per_day: int = 50


@dataclass
class BackfillSettings:
    generate_overview: bool = True


@dataclass
class SearchSettings:
    max_results: int = 50


@dataclass
class FavoritesSettings:
    enabled: bool = False
    keywords: List[str] = field(default_factory=list)
    ignore_keywords: List[str] = field(default_factory=list)


@dataclass
class Profile:
    categories: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    logic: str = "AND"
    topic_context: str = ""
    semantic_scholar_api_key: str = ""
    favorites: FavoritesSettings = field(default_factory=FavoritesSettings)
    daily: DailySettings = field(default_factory=DailySettings)
    backfill: BackfillSettings = field(default_factory=BackfillSettings)
    search: SearchSettings = field(default_factory=SearchSettings)


@dataclass
class ParsedListPage:
    listing_date: Optional[date]
    new_submission_ids: List[str]
    section_counts: Dict[str, Optional[int]]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def normalize_arxiv_id(raw_id: str) -> str:
    cleaned = raw_id.replace("arXiv:", "").strip()
    cleaned = cleaned.split("/abs/")[-1]
    return re.sub(r"v\d+$", "", cleaned)


def load_profile(profile_path: Path) -> Profile:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load arxiv profiles.")
    raw = yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}
    data = raw.get("arxiv") if isinstance(raw, dict) and isinstance(raw.get("arxiv"), dict) else raw
    daily = DailySettings(**(data.get("daily") or {}))
    backfill = BackfillSettings(**(data.get("backfill") or {}))
    search = SearchSettings(**(data.get("search") or {}))
    favorites = FavoritesSettings(**(data.get("favorites") or {}))
    logic = (data.get("logic") or "AND").upper()
    return Profile(
        categories=list(data.get("categories") or []),
        keywords=list(data.get("keywords") or []),
        exclude_keywords=list(data.get("exclude_keywords") or []),
        logic=logic if logic in {"AND", "OR"} else "AND",
        topic_context=str(data.get("topic_context") or "").strip(),
        semantic_scholar_api_key=str(data.get("semantic_scholar_api_key") or "").strip(),
        favorites=favorites,
        daily=daily,
        backfill=backfill,
        search=search,
    )


def _quote(term: str) -> str:
    term = term.strip()
    if re.search(r"[\s-]", term):
        return f'"{term}"'
    return term


def _field_or(term: str) -> str:
    query = _quote(term)
    return "(" + " OR ".join(f"{field}:{query}" for field in ("ti", "abs", "co")) + ")"


def _expand_variants(keyword: str) -> List[str]:
    keyword = keyword.strip()
    variants = {keyword}
    if " " in keyword:
        variants.add(keyword.replace(" ", "-"))
    if "-" in keyword:
        variants.add(keyword.replace("-", " "))
    return sorted(variants, key=len, reverse=True)


def _keyword_group(keyword: str) -> str:
    return "(" + " OR ".join(_field_or(variant) for variant in _expand_variants(keyword)) + ")"


def build_api_query(
    categories: Sequence[str],
    keywords: Sequence[str],
    exclude_keywords: Optional[Sequence[str]] = None,
    logic: str = "AND",
) -> str:
    categories = [item.strip() for item in categories if item and item.strip()]
    keywords = [item.strip() for item in keywords if item and item.strip()]
    exclude_keywords = [item.strip() for item in (exclude_keywords or []) if item and item.strip()]

    cat_query = "(" + " OR ".join(f"cat:{item}" for item in categories) + ")" if categories else ""
    kw_query = "(" + " OR ".join(_keyword_group(item) for item in keywords) + ")" if keywords else ""

    if cat_query and kw_query:
        positive = f"({cat_query} {(logic or 'AND').upper()} {kw_query})"
    elif cat_query:
        positive = cat_query
    elif kw_query:
        positive = kw_query
    else:
        positive = "all:*"

    if exclude_keywords:
        excludes = " OR ".join(_keyword_group(item) for item in exclude_keywords)
        return positive + f" AND NOT ({excludes})"
    return positive


def build_category_query(categories: Sequence[str]) -> str:
    categories = [item.strip() for item in categories if item and item.strip()]
    if not categories:
        return "all:*"
    return "(" + " OR ".join(f"cat:{item}" for item in categories) + ")"


def parse_new_list_page(html: str) -> ParsedListPage:
    listing_date = _extract_listing_date(html)
    section_counts = {
        "new": _extract_section_count(html, "New submissions"),
        "cross": _extract_section_count(html, "Cross submissions", "Cross-lists"),
        "replacement": _extract_section_count(html, "Replacement submissions", "Replacements"),
    }
    new_html = _extract_section_html(html, "New submissions")
    ids = [
        normalize_arxiv_id(raw_id)
        for raw_id in re.findall(r'href\s*=\s*"/abs/([^"]+)"[^>]*title\s*=\s*"Abstract"', new_html)
    ]
    return ParsedListPage(listing_date=listing_date, new_submission_ids=ids, section_counts=section_counts)


def _extract_listing_date(html: str) -> Optional[date]:
    match = re.search(
        r"Showing new listings for \w+,\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
        html,
    )
    if not match:
        return None
    day, month_name, year = match.groups()
    month_lookup = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    month = month_lookup.get(month_name)
    if not month:
        return None
    return date(int(year), month, int(day))


def _extract_section_count(html: str, *titles: str) -> Optional[int]:
    for title in titles:
        match = re.search(rf"{re.escape(title)} \(showing \d+ of (\d+) entries\)", html)
        if match:
            return int(match.group(1))
    return None


def _extract_section_html(html: str, title: str) -> str:
    pattern = rf"<h3>{re.escape(title)} \(showing \d+ of \d+ entries\)</h3>(.*?)(?=<h3>(?:Cross submissions|Cross-lists|Replacement submissions|Replacements)\b|</dl>)"
    match = re.search(pattern, html, re.DOTALL)
    return match.group(1) if match else ""


def plan_backfill_dates(start_date: str, end_date: str) -> List[date]:
    start = parse_date(start_date) if isinstance(start_date, str) else start_date
    end = parse_date(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        raise ValueError("to-date must be on or after from-date")
    dates = []
    cursor = start
    while cursor <= end:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def render_backfill_overview_markdown(
    daily_runs: Sequence[Dict[str, object]],
    date_from: str,
    date_to: str,
) -> str:
    lines = [
        "# Backfill Overview",
        "",
        f"- Date range: {date_from} -> {date_to}",
        f"- Total days: {len(daily_runs)}",
        f"- Total papers: {sum(int(item.get('count') or 0) for item in daily_runs)}",
        "",
        "## Daily Outputs",
        "",
    ]
    for item in daily_runs:
        lines.append(
            f"- {item['date']}: {item['count']} paper(s) -> {item['output_markdown']}"
        )
    return "\n".join(lines) + "\n"


def fetch_text(url: str, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "followhub-arxiv-collect/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
            "Accept": "application/atom+xml,application/xml,text/html;q=0.9,*/*;q=0.8",
        },
    )
    attempts = 6
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < attempts - 1:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt < attempts - 1:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise


def fetch_new_list_page(category: str) -> ParsedListPage:
    html = fetch_text(LIST_URL_TEMPLATE.format(category=urllib.parse.quote(category)))
    return parse_new_list_page(html)


def fetch_new_list_page_with_html(category: str) -> Tuple[ParsedListPage, str]:
    html = fetch_text(LIST_URL_TEMPLATE.format(category=urllib.parse.quote(category)))
    return parse_new_list_page(html), html


def fetch_new_list_pages(categories: Sequence[str]) -> Dict[str, ParsedListPage]:
    ordered_categories = [category for category in categories if category]
    if not ordered_categories:
        return {}
    if len(ordered_categories) == 1:
        category = ordered_categories[0]
        return {category: fetch_new_list_page(category)}

    workers = min(LIST_FETCH_MAX_WORKERS, len(ordered_categories))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        parsed = list(executor.map(fetch_new_list_page, ordered_categories))
    return dict(zip(ordered_categories, parsed))


def fetch_new_list_pages_with_html(categories: Sequence[str]) -> Tuple[Dict[str, ParsedListPage], Dict[str, str]]:
    ordered_categories = [category for category in categories if category]
    if not ordered_categories:
        return {}, {}
    workers = min(LIST_FETCH_MAX_WORKERS, len(ordered_categories))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(fetch_new_list_page_with_html, ordered_categories))
    parsed = {category: result[0] for category, result in zip(ordered_categories, results)}
    html_by_category = {category: result[1] for category, result in zip(ordered_categories, results)}
    return parsed, html_by_category


def fetch_feed_by_id_list(arxiv_ids: Sequence[str]) -> List[Dict[str, object]]:
    if not arxiv_ids:
        return []
    chunks = [arxiv_ids[index : index + API_ID_LIST_CHUNK_SIZE] for index in range(0, len(arxiv_ids), API_ID_LIST_CHUNK_SIZE)]
    if len(chunks) == 1:
        chunk = chunks[0]
        url = API_URL + "?" + urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": str(len(chunk))})
        return parse_atom_feed(fetch_text(url))

    def fetch_chunk(chunk: Sequence[str]) -> List[Dict[str, object]]:
        url = API_URL + "?" + urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": str(len(chunk))})
        return parse_atom_feed(fetch_text(url))

    entries: List[Dict[str, object]] = []
    for index, chunk in enumerate(chunks):
        if index:
            time.sleep(API_REQUEST_DELAY_SECONDS)
        page = fetch_chunk(chunk)
        entries.extend(page)
    return entries


def fetch_abs_metadata_by_id_list(
    arxiv_ids: Sequence[str],
    source_categories: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, object]]:
    ordered_ids = [normalize_arxiv_id(arxiv_id) for arxiv_id in arxiv_ids if arxiv_id]
    if not ordered_ids:
        return []

    def fetch_one(arxiv_id: str) -> Dict[str, object]:
        fallback_category = ""
        if source_categories:
            fallback_category = (source_categories.get(arxiv_id) or [""])[0]
        return fetch_abs_metadata(arxiv_id, fallback_category=fallback_category)

    workers = min(ABS_FETCH_MAX_WORKERS, len(ordered_ids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        entries = list(executor.map(fetch_one, ordered_ids))
    return entries


def fetch_abs_metadata(arxiv_id: str, fallback_category: str = "") -> Dict[str, object]:
    arxiv_id = normalize_arxiv_id(arxiv_id)
    html_url = ABS_URL_TEMPLATE.format(arxiv_id=urllib.parse.quote(arxiv_id))
    html = fetch_text(html_url)
    title = _first_meta_content(html, "citation_title") or _extract_labeled_block(html, "h1", "title")
    summary = _first_meta_content(html, "citation_abstract") or _extract_abstract_block(html)
    authors = _all_meta_content(html, "citation_author")
    if not authors:
        authors = _extract_abs_authors(html)
    published = _first_meta_content(html, "citation_date")
    if published:
        published = published.replace("/", "-")
    categories = _extract_subject_codes_from_html(html)
    if fallback_category and fallback_category not in categories:
        categories.insert(0, fallback_category)
    pdf_url = _first_meta_content(html, "citation_pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}"
    return {
        "id": arxiv_id,
        "entry_id": f"http://arxiv.org/abs/{arxiv_id}",
        "title": _clean_space(title.replace("Title:", "")) if title else arxiv_id,
        "summary": _clean_space(summary.replace("Abstract:", "")) if summary else "",
        "authors": authors,
        "categories": categories,
        "primary_category": categories[0] if categories else fallback_category or None,
        "published": published or "",
        "updated": published or "",
        "comments": _extract_comments_block(html),
        "html_url": html_url,
        "pdf_url": pdf_url,
        "metadata_source": "abs-page",
    }


def _html_unescape(text: str) -> str:
    import html

    return html.unescape(text or "")


def _first_meta_content(html: str, name: str) -> str:
    values = _all_meta_content(html, name)
    return values[0] if values else ""


def _all_meta_content(html: str, name: str) -> List[str]:
    values = []
    pattern = re.compile(
        rf"<meta\b(?=[^>]*\bname=[\"']{re.escape(name)}[\"'])(?=[^>]*\bcontent=[\"'](?P<content>.*?)[\"'])[^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        value = _clean_space(_html_unescape(match.group("content")))
        if value:
            values.append(value)
    return values


def _extract_labeled_block(html: str, tag: str, class_name: str) -> str:
    match = re.search(
        rf"<{tag}\\b[^>]*class=[\"'][^\"']*{re.escape(class_name)}[^\"']*[\"'][^>]*>(.*?)</{tag}>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return _strip_tags(match.group(1)) if match else ""


def _extract_abstract_block(html: str) -> str:
    match = re.search(
        r"<blockquote\b[^>]*class=[\"'][^\"']*abstract[^\"']*[\"'][^>]*>(.*?)</blockquote>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return _strip_tags(match.group(1)) if match else ""


def _extract_abs_authors(html: str) -> List[str]:
    match = re.search(
        r"<div\b[^>]*class=[\"'][^\"']*authors[^\"']*[\"'][^>]*>(.*?)</div>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    return [_clean_space(_html_unescape(item)) for item in re.findall(r">([^<>]+)</a>", match.group(1)) if _clean_space(item)]


def _extract_subject_codes_from_html(html: str) -> List[str]:
    match = re.search(
        r"<td\b[^>]*class=[\"'][^\"']*subjects[^\"']*[\"'][^>]*>(.*?)</td>|<span\b[^>]*class=[\"'][^\"']*primary-subject[^\"']*[\"'][^>]*>(.*?)</span>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    subject_html = " ".join(group for group in (match.groups() if match else []) if group)
    if not subject_html:
        subject_html = html
    text = _strip_tags(subject_html)
    codes = re.findall(r"\(([a-z-]+\.[A-Z]{2})\)", text)
    return _dedupe(codes)


def _extract_comments_block(html: str) -> str:
    match = re.search(
        r"<td\b[^>]*class=[\"'][^\"']*comments[^\"']*[\"'][^>]*>(.*?)</td>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return _strip_tags(match.group(1)) if match else ""


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def fetch_search_feed(
    search_query: str,
    *,
    start: int = 0,
    max_results: int = 50,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> List[Dict[str, object]]:
    params = {
        "search_query": search_query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    return parse_atom_feed(fetch_text(url))


def parse_atom_feed(xml_text: str) -> List[Dict[str, object]]:
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id = _entry_text(entry, "atom:id")
        arxiv_id = normalize_arxiv_id(entry_id or "")
        title = _clean_space(_entry_text(entry, "atom:title"))
        summary = _clean_space(_entry_text(entry, "atom:summary"))
        published = _entry_text(entry, "atom:published")
        updated = _entry_text(entry, "atom:updated")
        authors = [
            _clean_space(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        categories = [tag.attrib.get("term", "") for tag in entry.findall("atom:category", ATOM_NS)]
        primary_category = entry.find("arxiv:primary_category", ATOM_NS)
        comments = _entry_text(entry, "arxiv:comment")
        html_url, pdf_url = None, None
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.attrib.get("href")
            if link.attrib.get("rel") == "alternate":
                html_url = href
            if link.attrib.get("title", "").lower() == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = href
        entries.append(
            {
                "id": arxiv_id,
                "entry_id": entry_id,
                "title": title,
                "summary": summary,
                "authors": authors,
                "categories": [item for item in categories if item],
                "primary_category": primary_category.attrib.get("term") if primary_category is not None else None,
                "published": published,
                "updated": updated,
                "comments": comments,
                "html_url": html_url,
                "pdf_url": pdf_url,
            }
        )
    return entries


def _entry_text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS)


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_tags(html: str) -> str:
    return _clean_space(re.sub(r"<[^>]+>", " ", html))


def parse_new_list_entries(html: str, source_category: str) -> List[Dict[str, object]]:
    new_html = _extract_section_html(html, "New submissions")
    items: List[Dict[str, object]] = []
    pattern = re.compile(r"<dt>\s*(?P<dt>.*?)</dt>\s*<dd>\s*(?P<dd>.*?)</dd>", re.DOTALL)
    for match in pattern.finditer(new_html):
        dt = match.group("dt")
        dd = match.group("dd")
        id_match = re.search(r'href\s*=\s*"/abs/([^"]+)"', dt)
        if not id_match:
            continue
        arxiv_id = normalize_arxiv_id(id_match.group(1))
        title_match = re.search(r"<div class='list-title[^']*'.*?</span>\s*(.*?)</div>", dd, re.DOTALL)
        authors_match = re.search(r"<div class='list-authors'>(.*?)</div>", dd, re.DOTALL)
        subjects_match = re.search(r"<div class='list-subjects'.*?</span>\s*(.*?)</div>", dd, re.DOTALL)
        summary_match = re.search(r"<p class='mathjax'>\s*(.*?)</p>", dd, re.DOTALL)
        comment_match = re.search(r"<div class='list-comments[^']*'.*?</span>\s*(.*?)</div>", dd, re.DOTALL)

        subjects = _strip_tags(subjects_match.group(1)) if subjects_match else ""
        categories = re.findall(r"\(([a-z-]+\.[A-Z]{2})\)", subjects)
        if source_category not in categories:
            categories.insert(0, source_category)

        authors = re.findall(r">([^<>]+)</a>", authors_match.group(1)) if authors_match else []
        items.append(
            {
                "id": arxiv_id,
                "entry_id": f"http://arxiv.org/abs/{arxiv_id}",
                "title": _strip_tags(title_match.group(1)) if title_match else arxiv_id,
                "summary": _strip_tags(summary_match.group(1)) if summary_match else "",
                "authors": [_clean_space(author) for author in authors if _clean_space(author)],
                "categories": categories,
                "primary_category": categories[0] if categories else source_category,
                "published": "",
                "updated": "",
                "comments": _strip_tags(comment_match.group(1)) if comment_match else "",
                "html_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "source_categories": [source_category],
                "metadata_source": "list-page",
            }
        )
    return items


def merge_list_page_entries(pages: Dict[str, ParsedListPage], html_by_category: Dict[str, str]) -> List[Dict[str, object]]:
    by_id: Dict[str, Dict[str, object]] = {}
    for category in pages:
        for item in parse_new_list_entries(html_by_category[category], category):
            existing = by_id.setdefault(str(item["id"]), item)
            source_categories = list(existing.get("source_categories") or [])
            if category not in source_categories:
                source_categories.append(category)
            existing["source_categories"] = source_categories
    return list(by_id.values())


def score_entry(entry: Dict[str, object], profile: Profile) -> Dict[str, object]:
    text_title = str(entry.get("title") or "").lower()
    text_summary = str(entry.get("summary") or "").lower()
    combined = text_title + "\n" + text_summary
    excluded = [
        keyword for keyword in profile.exclude_keywords if keyword.lower() in combined
    ]
    matched_keywords = []
    score = 0.0
    for keyword in profile.keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in text_title:
            matched_keywords.append(keyword)
            score += 1.0
        elif keyword_lower in text_summary:
            matched_keywords.append(keyword)
            score += 0.6

    favorite_keywords = []
    favorite_ignores = []
    is_favorite = False
    is_ignored = False
    if profile.favorites.enabled:
        favorite_keywords = [
            keyword for keyword in profile.favorites.keywords if keyword.lower() in combined
        ]
        favorite_ignores = [
            keyword for keyword in profile.favorites.ignore_keywords if keyword.lower() in combined
        ]
        is_ignored = bool(favorite_ignores)
        is_favorite = bool(favorite_keywords) and not is_ignored
        if is_favorite:
            score += 0.8

    context_hits, context_score = context_feedback(entry, profile.topic_context)
    score += context_score
    categories = set(entry.get("categories") or [])
    if any(category in categories for category in profile.categories):
        score += 0.4

    scored = dict(entry)
    scored["matched_keywords"] = matched_keywords
    scored["matched_excludes"] = excluded
    scored["context_hits"] = context_hits
    scored["favorite_keywords"] = favorite_keywords
    scored["favorite_ignores"] = favorite_ignores
    scored["is_favorite"] = is_favorite
    scored["is_ignored"] = is_ignored
    scored["relevance_score"] = round(score, 2)
    scored["included"] = not excluded and (bool(matched_keywords) or not profile.keywords)
    return scored


def context_feedback(entry: Dict[str, object], topic_context: str) -> Tuple[List[str], float]:
    if not topic_context.strip():
        return [], 0.0
    entry_text = (str(entry.get("title") or "") + "\n" + str(entry.get("summary") or "")).lower()
    topic_terms = [
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", topic_context.lower())
        if term not in STOPWORDS
    ]
    unique_terms = []
    seen = set()
    for term in topic_terms:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)
    hits = [term for term in unique_terms if term in entry_text]
    score = min(1.0, len(hits) * 0.15)
    return hits[:8], round(score, 2)


def filter_and_sort_entries(entries: Sequence[Dict[str, object]], profile: Profile) -> List[Dict[str, object]]:
    scored = [score_entry(entry, profile) for entry in entries]
    scored.sort(
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            bool(item.get("is_favorite")),
            str(item.get("published") or ""),
        ),
        reverse=True,
    )
    return scored


def _date_window_query(base_query: str, target_day: date) -> str:
    day_token = target_day.strftime("%Y%m%d")
    window = f"submittedDate:[{day_token}0000 TO {day_token}2359]"
    return f"({base_query}) AND {window}"


def run_daily(profile: Profile, target_day: date) -> Dict[str, object]:
    today = datetime.now().date()
    if target_day != today:
        return run_backfill_day(profile, target_day, source_override="api-daily-fallback")

    source_categories: Dict[str, List[str]] = {}
    listing_date = None
    parsed_pages, html_by_category = fetch_new_list_pages_with_html(profile.categories)
    for category in profile.categories:
        parsed = parsed_pages[category]
        if listing_date is None:
            listing_date = parsed.listing_date
        for arxiv_id in parsed.new_submission_ids:
            source_categories.setdefault(arxiv_id, []).append(category)

    try:
        entries = fetch_abs_metadata_by_id_list(list(source_categories.keys()), source_categories)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout):
        entries = merge_list_page_entries(parsed_pages, html_by_category)
    for entry in entries:
        entry["source_categories"] = source_categories.get(entry["id"], [])
    ranked = filter_and_sort_entries(entries, profile)
    result = {
        "mode": "daily",
        "date": target_day.isoformat(),
        "source": "list-new",
        "listing_date": listing_date.isoformat() if listing_date else None,
        "raw_count": len(entries),
        "count": len(ranked),
        "entries": ranked,
    }
    return enrich_result_payload(result, profile)


def run_backfill_day(
    profile: Profile,
    target_day: date,
    *,
    source_override: str = "api-submitted-date",
) -> Dict[str, object]:
    query = build_category_query(profile.categories)
    day_query = _date_window_query(query, target_day)
    page_size = API_PAGE_SIZE
    start = 0
    collected: List[Dict[str, object]] = []

    while True:
        page = fetch_search_feed(day_query, start=start, max_results=page_size)
        if not page:
            break
        collected.extend(page)
        if len(page) < page_size:
            break
        start += page_size

    filtered = filter_and_sort_entries(collected, profile)
    same_day = [
        item
        for item in filtered
        if _entry_day(item.get("published")) == target_day
    ]
    result = {
        "mode": "daily",
        "date": target_day.isoformat(),
        "source": source_override,
        "listing_date": None,
        "raw_count": len(collected),
        "count": len(same_day),
        "entries": same_day,
    }
    return enrich_result_payload(result, profile)


def run_backfill(profile: Profile, start_day: date, end_day: date) -> Dict[str, object]:
    daily_runs = [run_backfill_day(profile, target_day) for target_day in plan_backfill_dates(start_day, end_day)]
    return {
        "mode": "backfill",
        "date_from": start_day.isoformat(),
        "date_to": end_day.isoformat(),
        "days": daily_runs,
    }


def run_search(profile: Profile, limit: Optional[int] = None) -> Dict[str, object]:
    max_results = limit or profile.search.max_results
    query = build_api_query(
        profile.categories,
        profile.keywords,
        profile.exclude_keywords,
        profile.logic,
    )
    collected: List[Dict[str, object]] = []
    start = 0
    page_size = min(100, max(25, max_results))
    while len(collected) < max_results:
        page = fetch_search_feed(query, start=start, max_results=page_size, sort_by="lastUpdatedDate")
        if not page:
            break
        collected.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    filtered = filter_and_sort_entries(collected, profile)
    result = {
        "mode": "search",
        "count": len(filtered[:max_results]),
        "entries": filtered[:max_results],
        "query": query,
    }
    return enrich_result_payload(result, profile)


def _entry_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _load_enrich_module():
    global _ENRICH_MODULE
    if _ENRICH_MODULE is not None:
        return None if _ENRICH_MODULE is False else _ENRICH_MODULE

    enrich_path = Path(__file__).resolve().parents[1] / "arxiv-enrich" / "arxiv_enrich.py"
    if not enrich_path.exists():
        _ENRICH_MODULE = False
        return None

    spec = importlib.util.spec_from_file_location("followhub_arxiv_enrich", enrich_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    _ENRICH_MODULE = module
    return module


def enrich_result_payload(payload: Dict[str, object], profile: Optional[Profile] = None) -> Dict[str, object]:
    module = _load_enrich_module()
    if module is None:
        return payload
    return module.enrich_payload(
        payload,
        enable_external_metadata=bool(profile and profile.semantic_scholar_api_key),
        semantic_scholar_api_key=(profile.semantic_scholar_api_key if profile else None),
        scoring_profile=profile,
    )


def render_daily_markdown(result: Dict[str, object]) -> str:
    lines = [
        f"# arXiv Daily Brief - {result['date']}",
        "",
        f"- Source: {result.get('source', 'unknown')}",
        f"- Papers: {result.get('count', 0)}",
        "",
    ]
    for index, entry in enumerate(result.get("entries") or [], start=1):
        lines.extend(
            [
                f"## {index}. {entry['title']}",
                "",
                f"- arXiv ID: {entry['id']}",
                f"- Authors: {', '.join(entry.get('authors') or []) or '—'}",
                f"- Categories: {', '.join(entry.get('categories') or []) or '—'}",
                f"- Relevance: {entry.get('relevance_score', 0)}",
                f"- Matched keywords: {', '.join(entry.get('matched_keywords') or []) or '—'}",
                f"- Favorite keywords: {', '.join(entry.get('favorite_keywords') or []) or '—'}",
                f"- Topic hits: {', '.join(entry.get('context_hits') or []) or '—'}",
                f"- PDF: {entry.get('pdf_url') or '—'}",
                "",
                entry.get("summary") or "",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_search_markdown(result: Dict[str, object]) -> str:
    lines = [
        "# arXiv Search Results",
        "",
        f"- Query: `{result.get('query', '')}`",
        f"- Papers: {result.get('count', 0)}",
        "",
    ]
    for index, entry in enumerate(result.get("entries") or [], start=1):
        lines.append(
            f"{index}. {entry['title']} ({entry['id']}) - relevance {entry.get('relevance_score', 0)}"
        )
    return "\n".join(lines) + "\n"


def write_outputs(result: Dict[str, object], output_dir: Path) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if result["mode"] == "daily":
        stem = f"{result['date']}-daily"
        json_path = output_dir / f"{stem}.json"
        markdown_path = output_dir / f"{stem}.md"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(render_daily_markdown(result), encoding="utf-8")
        return {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }

    if result["mode"] == "backfill":
        daily_runs = []
        for day in result["days"]:
            written = write_outputs(day, output_dir)
            daily_runs.append(
                {
                    "date": day["date"],
                    "count": day["count"],
                    "output_json": written["json"],
                    "output_markdown": written["markdown"],
                }
            )
        overview_path = output_dir / f"{result['date_from']}_to_{result['date_to']}-backfill-overview.md"
        overview_text = render_backfill_overview_markdown(
            daily_runs=daily_runs,
            date_from=result["date_from"],
            date_to=result["date_to"],
        )
        overview_path.write_text(overview_text, encoding="utf-8")
        return {
            "daily_runs": daily_runs,
            "overview_markdown": str(overview_path),
        }

    if result["mode"] == "search":
        stem = f"search-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        json_path = output_dir / f"{stem}.json"
        markdown_path = output_dir / f"{stem}.md"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(render_search_markdown(result), encoding="utf-8")
        return {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }

    raise ValueError(f"Unsupported mode: {result['mode']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-collect", add_help=True)
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate-profile")
    validate.add_argument("--profile", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=["daily", "backfill", "search"], required=True)
    run.add_argument("--profile", required=True)
    run.add_argument("--date")
    run.add_argument("--from-date")
    run.add_argument("--to-date")
    run.add_argument("--output-dir", default="arxiv-collect-output")
    run.add_argument("--keywords")
    run.add_argument("--categories")
    run.add_argument("--exclude-keywords")
    run.add_argument("--max-results", type=int)

    return parser


def apply_cli_overrides(profile: Profile, args: argparse.Namespace) -> Profile:
    if getattr(args, "keywords", None):
        profile.keywords = split_csv(args.keywords)
    if getattr(args, "categories", None):
        profile.categories = split_csv(args.categories)
    if getattr(args, "exclude_keywords", None):
        profile.exclude_keywords = split_csv(args.exclude_keywords)
    if getattr(args, "max_results", None):
        profile.search.max_results = args.max_results
        profile.daily.max_results_per_day = args.max_results
    return profile


def split_csv(raw: str) -> List[str]:
    return [item.strip() for item in re.split(r"\s*,\s*|\s*;\s*", raw) if item.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-profile":
        profile = load_profile(Path(args.profile))
        print(json.dumps(asdict(profile), ensure_ascii=False, indent=2))
        return 0

    if args.command == "run":
        profile = apply_cli_overrides(load_profile(Path(args.profile)), args)
        output_dir = Path(args.output_dir)
        if args.mode == "daily":
            target_day = parse_date(args.date) if args.date else datetime.now().date()
            result = run_daily(profile, target_day)
        elif args.mode == "backfill":
            if not args.from_date or not args.to_date:
                raise SystemExit("--from-date and --to-date are required for backfill mode")
            result = run_backfill(profile, parse_date(args.from_date), parse_date(args.to_date))
        elif args.mode == "search":
            result = run_search(profile, args.max_results)
        else:  # pragma: no cover
            raise SystemExit(f"Unsupported mode: {args.mode}")

        written = write_outputs(result, output_dir)
        print(json.dumps({"result": result, "written": written}, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
