#!/usr/bin/env python3
"""
arxiv_find.py - Hybrid arXiv retrieval for daily briefs, backfills, and search.
"""

import argparse
import json
import re
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
API_URL = "https://export.arxiv.org/api/query"
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
arxiv-find: Hybrid arXiv retrieval for daily briefs, backfills, and search.

Usage:
    arxiv-find help
    arxiv-find validate-profile --profile /path/to/arxiv-profile.yaml
    arxiv-find run --mode daily --profile /path/to/arxiv-profile.yaml
    arxiv-find run --mode backfill --profile /path/to/arxiv-profile.yaml --from-date YYYY-MM-DD --to-date YYYY-MM-DD
    arxiv-find run --mode search --profile /path/to/arxiv-profile.yaml [--keywords "kw1,kw2"]

Modes:
    daily     Prefer arXiv list/new pages and keep only New submissions.
    backfill  Use one submittedDate API window per day and keep each day separate.
    search    Use API query mode with pagination and shared profile filters.
"""


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
    data = yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}
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
            "User-Agent": "followhub-arxiv-find/0.1 (+https://github.com/Greyman-Seu/Greyman-Seu.github.io)",
            "Accept": "application/atom+xml,application/xml,text/html;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_new_list_page(category: str) -> ParsedListPage:
    html = fetch_text(LIST_URL_TEMPLATE.format(category=urllib.parse.quote(category)))
    return parse_new_list_page(html)


def fetch_feed_by_id_list(arxiv_ids: Sequence[str]) -> List[Dict[str, object]]:
    if not arxiv_ids:
        return []
    chunks = [arxiv_ids[index : index + 50] for index in range(0, len(arxiv_ids), 50)]
    entries: List[Dict[str, object]] = []
    for chunk in chunks:
        url = API_URL + "?" + urllib.parse.urlencode({"id_list": ",".join(chunk)})
        entries.extend(parse_atom_feed(fetch_text(url)))
    return entries


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
    kept = [entry for entry in scored if entry["included"]]
    kept.sort(
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            str(item.get("published") or ""),
        ),
        reverse=True,
    )
    return kept


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
    for category in profile.categories:
        parsed = fetch_new_list_page(category)
        if listing_date is None:
            listing_date = parsed.listing_date
        for arxiv_id in parsed.new_submission_ids[: profile.daily.max_results_per_day]:
            source_categories.setdefault(arxiv_id, []).append(category)

    entries = fetch_feed_by_id_list(list(source_categories.keys()))
    for entry in entries:
        entry["source_categories"] = source_categories.get(entry["id"], [])
    filtered = filter_and_sort_entries(entries, profile)
    return {
        "mode": "daily",
        "date": target_day.isoformat(),
        "source": "list-new",
        "listing_date": listing_date.isoformat() if listing_date else None,
        "count": len(filtered),
        "entries": filtered[: profile.daily.max_results_per_day],
    }


def run_backfill_day(
    profile: Profile,
    target_day: date,
    *,
    source_override: str = "api-submitted-date",
) -> Dict[str, object]:
    query = build_api_query(
        profile.categories,
        profile.keywords,
        profile.exclude_keywords,
        profile.logic,
    )
    day_query = _date_window_query(query, target_day)
    page_size = min(100, max(25, profile.daily.max_results_per_day))
    start = 0
    collected: List[Dict[str, object]] = []

    while len(collected) < profile.daily.max_results_per_day:
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
    return {
        "mode": "daily",
        "date": target_day.isoformat(),
        "source": source_override,
        "listing_date": None,
        "count": len(same_day[: profile.daily.max_results_per_day]),
        "entries": same_day[: profile.daily.max_results_per_day],
    }


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
    return {
        "mode": "search",
        "count": len(filtered[:max_results]),
        "entries": filtered[:max_results],
        "query": query,
    }


def _entry_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


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
    parser = argparse.ArgumentParser(prog="arxiv-find", add_help=True)
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate-profile")
    validate.add_argument("--profile", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=["daily", "backfill", "search"], required=True)
    run.add_argument("--profile", required=True)
    run.add_argument("--date")
    run.add_argument("--from-date")
    run.add_argument("--to-date")
    run.add_argument("--output-dir", default="arxiv-find-output")
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
