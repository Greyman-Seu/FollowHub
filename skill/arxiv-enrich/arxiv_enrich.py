#!/usr/bin/env python3
"""
arxiv_enrich.py - Enrich arxiv-find result payloads into a stable shared contract.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None


HELP_TEXT = """\
arxiv-enrich: Enrich arxiv-find outputs into the shared FollowHub contract.

Usage:
    arxiv-enrich help
    arxiv-enrich enrich --input /path/to/arxiv-find-output.json --output /path/to/enriched.json [--profile /path/to/profile.yaml]
"""

CODE_HOSTS = (
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "gitee.com",
    "huggingface.co",
    "sourceforge.net",
    "sr.ht",
    "git.sr.ht",
)
TRAILING_CHARS = '.,;:?!)]}>\'"'
URL_PAT = re.compile(r"https?://[^\s)\]>\'\"`]+", re.IGNORECASE)
LABELED_URL_PATTERNS = {
    "project_urls": re.compile(r"project(?:\s+page)?\s*:\s*(https?://[^\s)\]>\'\"`]+)", re.IGNORECASE),
    "code_urls": re.compile(r"code\s*:\s*(https?://[^\s)\]>\'\"`]+)", re.IGNORECASE),
}
ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = "title,abstract,citationCount,influentialCitationCount,url,authors,authors.affiliations,externalIds"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
AFFILIATION_HINTS = (
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
    "microsoft",
    "google",
    "deepmind",
    "stanford",
    "tsinghua",
    "peking",
    "mit",
    "cmu",
    "nvidia",
)
SCORE_MAX = 3.0
RELEVANCE_TITLE_KEYWORD_BOOST = 0.5
RELEVANCE_SUMMARY_KEYWORD_BOOST = 0.3
RELEVANCE_CATEGORY_MATCH_BOOST = 1.0
FAVORITE_MATCH_BOOST = 0.8
RECENCY_THRESHOLDS = [
    (7, 3.0),
    (14, 2.2),
    (30, 1.4),
    (90, 0.7),
]
RECENCY_DEFAULT = 0.0
TOPIC_STOPWORDS = {
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


def _clean_url(url: str) -> str:
    while url and url[-1] in TRAILING_CHARS:
        url = url[:-1]
    return url


def _host_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_code_host(host: str) -> bool:
    return any(host == code_host or host.endswith("." + code_host) for code_host in CODE_HOSTS)


def _is_project_like(url: str, host: str) -> bool:
    if re.search(r"\.(?:io|ai|ml)$", host):
        return True
    if "sites.google.com" in host:
        return True
    if any(token in host for token in (".cs.", ".vision.", ".ee.", ".cv.", ".ml.")):
        return True
    return bool(
        re.search(r"/(project|projects|page|pages|people|lab|group|research|paper|papers)(/|$)", url, re.IGNORECASE)
    )


def _dedup_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def extract_urls(text: str) -> Dict[str, List[str]]:
    cleaned = [_clean_url(url) for url in URL_PAT.findall(text or "")]
    code_urls: List[str] = []
    project_urls: List[str] = []
    for url in LABELED_URL_PATTERNS["code_urls"].findall(text or ""):
        code_urls.append(_clean_url(url))
    for url in LABELED_URL_PATTERNS["project_urls"].findall(text or ""):
        project_urls.append(_clean_url(url))
    for url in cleaned:
        host = _host_of(url)
        if not host:
            continue
        if _is_code_host(host):
            code_urls.append(url)
        elif _is_project_like(url, host):
            project_urls.append(url)
    return {
        "code_urls": _dedup_keep_order(code_urls),
        "project_urls": _dedup_keep_order(project_urls),
    }


def _first_sentence_zh(text: str) -> str:
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[。！？!?])\s*", compact)
    return parts[0].strip() if parts and parts[0].strip() else compact


def _coerce_affiliations(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"\s*;\s*|\s*\|\s*|\s*\n\s*", value.strip())
        return [part for part in parts if part]
    return []


def build_author_meta(authors: Any, affiliations: List[str]) -> List[Dict[str, Any]]:
    author_names = _listify(authors)
    if not author_names:
        return []
    first_author_affiliations = affiliations[:1] if affiliations else []
    items = []
    for index, name in enumerate(author_names):
        items.append(
            {
                "name": name,
                "affiliations": first_author_affiliations if index == 0 else [],
                "is_first_author": index == 0,
                "is_corresponding_author": False,
            }
        )
    return items


def build_author_meta_from_semantic_scholar(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for index, author in enumerate(metadata.get("authors") or []):
        if isinstance(author, dict):
            name = str(author.get("name") or "").strip()
            raw_affiliations = author.get("affiliations") or []
        else:
            name = str(author).strip()
            raw_affiliations = []
        if not name:
            continue
        affiliations = []
        for affiliation in raw_affiliations:
            if isinstance(affiliation, dict):
                value = str(affiliation.get("name") or "").strip()
            else:
                value = str(affiliation).strip()
            if value:
                affiliations.append(value)
        items.append(
            {
                "name": name,
                "affiliations": _dedup_keep_order(affiliations),
                "is_first_author": index == 0,
                "is_corresponding_author": False,
            }
        )
    return items


def mark_corresponding_authors(author_meta: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    if not author_meta:
        return author_meta
    lowered = str(text or "").lower()
    if not any(token in lowered for token in ("corresponding", "correspondence", "contact author", "contact:")):
        return author_meta
    items = [dict(author) for author in author_meta]
    if len(items) == 1:
        items[0]["is_corresponding_author"] = True
        return items
    matched = False
    for author in items:
        name = str(author.get("name") or "").strip()
        if not name:
            continue
        surname = name.split()[-1].lower()
        if surname and surname in lowered:
            author["is_corresponding_author"] = True
            matched = True
    return items if matched else author_meta


def _cleanup_affiliation_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b([A-Za-z]+)of([A-Z][a-z])", r"\1 of \2", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_affiliations_from_text(text: str) -> List[str]:
    if not text:
        return []
    normalized = _cleanup_affiliation_text(text)
    raw_lines = []
    for line in normalized.splitlines():
        line = line.strip()
        if not line:
            continue
        raw_lines.extend(part.strip() for part in re.split(r"(?=\b\d+\s+[A-Z])", line) if part.strip())
    candidates: List[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[\d\W_]+", "", line).strip()
        if not line:
            continue
        if re.search(r"\b[a-zA-Z]{18,}\b", line):
            continue
        lowered = line.lower()
        if any(token in lowered for token in AFFILIATION_HINTS):
            candidates.append(line)
    return _dedup_keep_order(candidates)


def extract_affiliations_from_semantic_scholar(metadata: Dict[str, Any]) -> List[str]:
    affiliations: List[str] = []
    for author in metadata.get("authors") or []:
        for affiliation in author.get("affiliations") or []:
            if isinstance(affiliation, dict):
                name = str(affiliation.get("name") or "").strip()
            else:
                name = str(affiliation).strip()
            if name:
                affiliations.append(name)
    return _dedup_keep_order(affiliations)


def _field(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _listify(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"\s*,\s*|\s*;\s*", value) if item.strip()]
    return []


def normalize_scoring_profile(profile: Any) -> Dict[str, Any]:
    if isinstance(profile, dict) and "domains" in profile:
        return {
            "domains": {
                str(domain_name): {
                    "keywords": _listify(domain_config.get("keywords", [])),
                    "categories": _listify(domain_config.get("categories", [])),
                }
                for domain_name, domain_config in (profile.get("domains") or {}).items()
            },
            "excluded_keywords": _listify(profile.get("excluded_keywords", [])),
            "topic_context": str(profile.get("topic_context", "") or "").strip(),
            "favorites_enabled": bool(profile.get("favorites_enabled", False)),
            "favorite_keywords": _listify(profile.get("favorite_keywords", [])),
            "favorite_ignore_keywords": _listify(profile.get("favorite_ignore_keywords", [])),
        }

    domains: Dict[str, Dict[str, List[str]]] = {}

    research_domains = _field(profile, "research_domains", {}) or {}
    if isinstance(research_domains, dict):
        for domain_name, domain_config in research_domains.items():
            domains[str(domain_name)] = {
                "keywords": _listify(_field(domain_config, "keywords", [])),
                "categories": _listify(
                    _field(domain_config, "arxiv_categories", _field(domain_config, "categories", []))
                ),
            }

    top_level_keywords = _listify(_field(profile, "keywords", []))
    top_level_categories = _listify(_field(profile, "categories", []))
    if top_level_keywords or top_level_categories:
        domains["default"] = {
            "keywords": top_level_keywords,
            "categories": top_level_categories,
        }

    favorites = _field(profile, "favorites", {}) or {}
    normalized = {
        "domains": domains,
        "excluded_keywords": _listify(
            _field(profile, "excluded_keywords", _field(profile, "exclude_keywords", []))
        ),
        "topic_context": str(_field(profile, "topic_context", "") or "").strip(),
        "favorites_enabled": bool(_field(favorites, "enabled", False)),
        "favorite_keywords": _listify(_field(favorites, "keywords", [])),
        "favorite_ignore_keywords": _listify(_field(favorites, "ignore_keywords", [])),
    }
    return normalized


def load_scoring_profile(profile_path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load enrich scoring profiles.")
    raw = yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}
    return normalize_scoring_profile(raw)


def _expand_variants(keyword: str) -> List[str]:
    keyword = keyword.strip().lower()
    variants = {keyword}
    if " " in keyword:
        variants.add(keyword.replace(" ", "-"))
    if "-" in keyword:
        variants.add(keyword.replace("-", " "))
    return sorted(variants, key=len, reverse=True)


def _extract_acronyms(text: str) -> List[str]:
    acronyms = set()
    for phrase in re.findall(r"[a-z]+(?:-[a-z]+)+", text.lower()):
        parts = [part for part in phrase.split("-") if part]
        if len(parts) >= 2:
            acronyms.add("".join(part[0] for part in parts))
    for phrase in re.findall(r"[a-z]+(?:\s+[a-z]+){1,4}", text.lower()):
        parts = [part for part in phrase.split() if part]
        if len(parts) >= 2:
            acronyms.add("".join(part[0] for part in parts))
    return sorted(acronyms)


def _contains_keyword(text: str, keyword: str) -> bool:
    lowered = text.lower()
    if any(variant and variant in lowered for variant in _expand_variants(keyword)):
        return True
    compact_keyword = re.sub(r"[^a-z0-9]", "", keyword.lower())
    if compact_keyword.isalpha() and 2 <= len(compact_keyword) <= 6:
        return compact_keyword in _extract_acronyms(lowered)
    return False


def classify_favorite(entry: Dict[str, Any], scoring_profile: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{entry.get('title', '')}\n{entry.get('summary', '')}\n{entry.get('abstract', '')}".lower()
    favorite_keywords = [
        keyword for keyword in scoring_profile.get("favorite_keywords", []) if _contains_keyword(text, keyword)
    ]
    favorite_ignores = [
        keyword for keyword in scoring_profile.get("favorite_ignore_keywords", []) if _contains_keyword(text, keyword)
    ]
    is_ignored = bool(favorite_ignores)
    is_favorite = bool(favorite_keywords) and not is_ignored
    return {
        "favorite_keywords": favorite_keywords,
        "favorite_ignores": favorite_ignores,
        "is_favorite": is_favorite,
        "is_ignored": is_ignored,
    }


def context_feedback(entry: Dict[str, Any], topic_context: str) -> Tuple[List[str], float]:
    if not topic_context.strip():
        return [], 0.0
    entry_text = (
        str(entry.get("title") or "")
        + "\n"
        + str(entry.get("summary") or entry.get("abstract") or entry.get("abstract_en") or "")
    ).lower()
    topic_terms = [
        term
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", topic_context.lower())
        if term not in TOPIC_STOPWORDS
    ]
    unique_terms: List[str] = []
    seen = set()
    for term in topic_terms:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)
    hits = [term for term in unique_terms if term in entry_text]
    score = min(1.0, len(hits) * 0.15)
    return hits[:8], round(score, 2)


def calculate_relevance_score(
    entry: Dict[str, Any],
    scoring_profile: Dict[str, Any],
) -> Tuple[float, Optional[str], List[str], List[str], List[str], Dict[str, Any]]:
    title = str(entry.get("title") or "").lower()
    summary = str(entry.get("summary") or entry.get("abstract") or entry.get("abstract_en") or "").lower()
    combined = title + "\n" + summary
    categories = set(entry.get("categories") or [])

    matched_excludes = [
        keyword for keyword in scoring_profile.get("excluded_keywords", []) if _contains_keyword(combined, keyword)
    ]
    if matched_excludes:
        favorite_meta = classify_favorite(entry, scoring_profile)
        return 0.0, None, [], matched_excludes, [], favorite_meta

    best_score = 0.0
    best_domain = None
    best_keywords: List[str] = []
    matched_categories: List[str] = []

    for domain_name, domain_config in (scoring_profile.get("domains") or {}).items():
        score = 0.0
        domain_keywords: List[str] = []
        domain_categories: List[str] = []

        for keyword in domain_config.get("keywords", []):
            if _contains_keyword(title, keyword):
                score += RELEVANCE_TITLE_KEYWORD_BOOST
                domain_keywords.append(keyword)
            elif _contains_keyword(summary, keyword):
                score += RELEVANCE_SUMMARY_KEYWORD_BOOST
                domain_keywords.append(keyword)

        for category in domain_config.get("categories", []):
            if category in categories:
                score += RELEVANCE_CATEGORY_MATCH_BOOST
                domain_categories.append(category)

        if score > best_score:
            best_score = score
            best_domain = domain_name
            best_keywords = _dedup_keep_order(domain_keywords)
            matched_categories = _dedup_keep_order(domain_categories)

    context_hits, context_score = context_feedback(entry, scoring_profile.get("topic_context", ""))
    favorite_meta = classify_favorite(entry, scoring_profile)
    best_score += context_score
    if favorite_meta["is_favorite"]:
        best_score += FAVORITE_MATCH_BOOST

    return (
        round(min(best_score, SCORE_MAX), 2),
        best_domain,
        _dedup_keep_order(best_keywords + matched_categories),
        matched_excludes,
        context_hits,
        favorite_meta,
    )


def build_agent_translation_prompt(title: str, abstract_en: str) -> str:
    return (
        "Translate the English abstract into Chinese.\n\n"
        "Required output keys:\n"
        "- summary_cn: a faithful Chinese translation of the English abstract\n\n"
        "Rules:\n"
        "- Do not invent facts beyond the abstract\n"
        "- Keep summary_cn faithful to the abstract rather than rewriting it as a new summary\n"
        "- Preserve technical meaning and key claims\n"
        "- Return structured values for summary_cn only\n\n"
        f"Title: {title}\n\n"
        f"Abstract: {abstract_en}\n"
    )


def build_agent_one_liner_prompt(title: str, abstract_en: str) -> str:
    return (
        "Write one concise Chinese line for quick scanning.\n\n"
        "Required output keys:\n"
        "- one_liner_zh: one concise Chinese sentence, easy to skim\n\n"
        "Rules:\n"
        "- Do not invent facts beyond the abstract\n"
        "- Keep one_liner_zh short and direct\n"
        "- Focus on the paper's core method or contribution\n"
        "- Return structured values for one_liner_zh only\n\n"
        f"Title: {title}\n\n"
        f"Abstract: {abstract_en}\n"
    )


def calculate_quality_score(title: str, abstract_en: str) -> float:
    text = f"{title} {abstract_en}".lower()
    score = 0.0

    strong_innovation = [
        "state-of-the-art",
        "sota",
        "breakthrough",
        "first",
        "surpass",
        "outperform",
        "pioneering",
    ]
    weak_innovation = [
        "novel",
        "propose",
        "introduce",
        "new approach",
        "new method",
        "framework",
    ]
    evaluation_terms = [
        "benchmark",
        "evaluation",
        "experiment",
        "ablation",
        "accuracy",
        "success rate",
        "f1",
        "bleu",
        "rouge",
    ]

    strong_count = sum(1 for token in strong_innovation if token in text)
    weak_count = sum(1 for token in weak_innovation if token in text)
    eval_count = sum(1 for token in evaluation_terms if token in text)

    if strong_count >= 1:
        score += 1.2
    elif weak_count >= 1:
        score += 0.7

    if eval_count >= 2:
        score += 1.0
    elif eval_count == 1:
        score += 0.5

    if "robot" in text or "vision-language-action" in text or "vla" in text:
        score += 0.3

    return round(min(score, 3.0), 2)


def calculate_recency_score(published_value: str) -> float:
    if not published_value:
        return RECENCY_DEFAULT
    normalized = published_value.replace("Z", "+00:00")
    try:
        published_at = datetime.fromisoformat(normalized)
    except ValueError:
        return RECENCY_DEFAULT
    now = datetime.now(published_at.tzinfo) if published_at.tzinfo else datetime.now()
    days_diff = max(0, (now - published_at).days)
    for max_days, score in RECENCY_THRESHOLDS:
        if days_diff <= max_days:
            return score
    return RECENCY_DEFAULT


def calculate_overall_score(
    relevance_score: float,
    hot_score: float,
    quality_score: float,
    recency_score: float = 0.0,
) -> float:
    if not any([relevance_score, hot_score, quality_score, recency_score]):
        return 0.0
    overall = (
        (relevance_score * 0.4)
        + (recency_score * 0.15)
        + (hot_score * 0.25)
        + (quality_score * 0.2)
    )
    return round(overall, 2)


def calculate_hot_score(
    citation_count: int,
    influential_citation_count: int,
    existing_hot_score: float = 0.0,
    recency_score: float = 0.0,
) -> float:
    if existing_hot_score:
        return round(existing_hot_score, 2)
    if not citation_count and not influential_citation_count:
        if recency_score >= 3.0:
            return 2.0
        if recency_score >= 2.2:
            return 1.5
        if recency_score >= 1.4:
            return 1.0
        if recency_score > 0:
            return 0.5
        return 0.0
    influential_component = min(2.0, influential_citation_count / 4.0)
    citation_component = min(1.0, citation_count / 100.0)
    return round(min(3.0, influential_component + citation_component), 2)


def resolve_semantic_scholar_api_key(explicit_key: Optional[str] = None) -> str:
    if explicit_key:
        return explicit_key
    return os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()


def title_similarity(a: str, b: str) -> float:
    def normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).strip()

    a_norm = normalize(a)
    b_norm = normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    words_a = set(a_norm.split())
    words_b = set(b_norm.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _entry_text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS)


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_arxiv_id(raw_id: str) -> str:
    cleaned = raw_id.replace("arXiv:", "").strip()
    cleaned = cleaned.split("/abs/")[-1]
    return re.sub(r"v\d+$", "", cleaned)


def fetch_text(url: str, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "followhub-arxiv-enrich/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
            "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_semantic_scholar_metadata(
    *,
    title: str,
    api_key: str,
    timeout: int = 15,
    limit: int = 3,
) -> Dict[str, Any]:
    if not api_key or not title.strip():
        return {}

    params = urllib.parse.urlencode(
        {
            "query": title,
            "limit": limit,
            "fields": SEMANTIC_SCHOLAR_FIELDS,
        }
    )
    request = urllib.request.Request(
        f"{SEMANTIC_SCHOLAR_API_URL}?{params}",
        headers={
            "User-Agent": "followhub-arxiv-enrich/0.1 (+https://github.com/Greyman-Seu/FollowHub)",
            "x-api-key": api_key,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results = payload.get("data") or []
    best_match = None
    best_score = 0.0
    for candidate in results:
        score = title_similarity(title, candidate.get("title", ""))
        if score > best_score:
            best_score = score
            best_match = candidate
    if best_match and best_score >= 0.6:
        return best_match
    return {}


def parse_atom_feed(xml_text: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id = _entry_text(entry, "atom:id")
        arxiv_id = normalize_arxiv_id(entry_id or "")
        html_url, pdf_url = None, None
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.attrib.get("href")
            if link.attrib.get("rel") == "alternate":
                html_url = href
            if link.attrib.get("title", "").lower() == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = href
        items.append(
            {
                "id": arxiv_id,
                "entry_id": entry_id,
                "title": _clean_space(_entry_text(entry, "atom:title")),
                "summary": _clean_space(_entry_text(entry, "atom:summary")),
                "authors": [
                    _clean_space(author.findtext("atom:name", default="", namespaces=ATOM_NS))
                    for author in entry.findall("atom:author", ATOM_NS)
                ],
                "categories": [
                    item.attrib.get("term", "")
                    for item in entry.findall("atom:category", ATOM_NS)
                    if item.attrib.get("term")
                ],
                "published": _entry_text(entry, "atom:published"),
                "updated": _entry_text(entry, "atom:updated"),
                "comments": _entry_text(entry, "arxiv:comment"),
                "pdf_url": pdf_url,
                "html_url": html_url,
            }
        )
    return items


def fetch_entries_by_ids(arxiv_ids: List[str]) -> List[Dict[str, Any]]:
    if not arxiv_ids:
        return []
    chunks = [arxiv_ids[index : index + 50] for index in range(0, len(arxiv_ids), 50)]
    items: List[Dict[str, Any]] = []
    for chunk in chunks:
        query = urllib.parse.urlencode({"id_list": ",".join(chunk)})
        xml_text = fetch_text(f"{ARXIV_API_URL}?{query}")
        items.extend(parse_atom_feed(xml_text))
    return items


def split_ids(raw: str) -> List[str]:
    return [item.strip() for item in re.split(r"\s*,\s*|\s*;\s*|\s+", raw or "") if item.strip()]


def build_payload_from_ids(arxiv_ids: List[str]) -> Dict[str, Any]:
    entries = fetch_entries_by_ids(arxiv_ids)
    return {
        "mode": "search",
        "count": len(entries),
        "query": f"id_list:{','.join(arxiv_ids)}",
        "entries": entries,
    }


def enrich_entry(
    entry: Dict[str, Any],
    *,
    enable_external_metadata: bool = False,
    semantic_scholar_api_key: Optional[str] = None,
    scoring_profile: Optional[Any] = None,
) -> Dict[str, Any]:
    enriched = dict(entry)
    semantic_scholar = dict(enriched.get("semantic_scholar") or {})
    normalized_profile = normalize_scoring_profile(scoring_profile) if scoring_profile else None
    api_key = resolve_semantic_scholar_api_key(semantic_scholar_api_key)
    if enable_external_metadata and not semantic_scholar and api_key and enriched.get("title"):
        try:
            semantic_scholar = fetch_semantic_scholar_metadata(
                title=str(enriched.get("title") or ""),
                api_key=api_key,
            )
        except Exception:
            semantic_scholar = {}
    abstract_en = (
        enriched.get("abstract_en")
        or enriched.get("summary")
        or enriched.get("abstract")
        or semantic_scholar.get("abstract")
        or ""
    )
    summary_cn = enriched.get("summary_cn") or enriched.get("digest_zh") or ""
    one_liner_zh = enriched.get("one_liner_zh") or _first_sentence_zh(summary_cn)
    affiliations = _coerce_affiliations(enriched.get("affiliations"))
    if not affiliations and semantic_scholar:
        affiliations = extract_affiliations_from_semantic_scholar(semantic_scholar)
    if not affiliations:
        affiliations = extract_affiliations_from_text(
            "\n".join(
                [
                    str(enriched.get("pdf_first_pages_text") or ""),
                    str(enriched.get("pdf_head_text") or ""),
                    str(enriched.get("html_text") or ""),
                ]
            )
        )
    first_affiliation = enriched.get("first_affiliation") or (affiliations[0] if affiliations else "")
    author_meta = enriched.get("author_meta") or []
    if not author_meta and semantic_scholar:
        author_meta = build_author_meta_from_semantic_scholar(semantic_scholar)
    if not author_meta:
        author_meta = build_author_meta(enriched.get("authors"), affiliations)
    author_meta = mark_corresponding_authors(
        author_meta,
        "\n".join(
            [
                str(enriched.get("comments") or ""),
                str(enriched.get("html_text") or ""),
                str(enriched.get("pdf_head_text") or ""),
            ]
        ),
    )

    url_source = "\n".join(
        [
            str(enriched.get("comments") or ""),
            str(abstract_en or ""),
            str(enriched.get("html_url") or ""),
            str(enriched.get("html_text") or ""),
            str(enriched.get("pdf_head_text") or ""),
        ]
    )
    extracted_urls = extract_urls(url_source)
    code_urls = _dedup_keep_order(list(enriched.get("code_urls") or []) + extracted_urls["code_urls"])
    project_urls = _dedup_keep_order(list(enriched.get("project_urls") or []) + extracted_urls["project_urls"])

    citation_count = int(
        enriched.get(
            "citation_count",
            enriched.get("citationCount", semantic_scholar.get("citationCount", 0)),
        )
        or 0
    )
    influential_citation_count = int(
        enriched.get(
            "influential_citation_count",
            enriched.get("influentialCitationCount", semantic_scholar.get("influentialCitationCount", 0)),
        )
        or 0
    )
    relevance_score = float(enriched.get("relevance_score", 0) or 0)
    matched_domain = enriched.get("matched_domain")
    matched_keywords = list(enriched.get("matched_keywords") or [])
    matched_excludes = list(enriched.get("matched_excludes") or [])
    context_hits = list(enriched.get("context_hits") or [])
    favorite_keywords = list(enriched.get("favorite_keywords") or [])
    favorite_ignores = list(enriched.get("favorite_ignores") or [])
    is_favorite = bool(enriched.get("is_favorite", False))
    is_ignored = bool(enriched.get("is_ignored", False))
    if normalized_profile:
        (
            relevance_score,
            matched_domain,
            matched_keywords,
            matched_excludes,
            context_hits,
            favorite_meta,
        ) = calculate_relevance_score(enriched, normalized_profile)
        favorite_keywords = favorite_meta["favorite_keywords"]
        favorite_ignores = favorite_meta["favorite_ignores"]
        is_favorite = favorite_meta["is_favorite"]
        is_ignored = favorite_meta["is_ignored"]
    recency_score = float(enriched.get("recency_score", 0) or 0)
    if not recency_score:
        recency_score = calculate_recency_score(str(enriched.get("published") or enriched.get("updated") or ""))
    hot_score = calculate_hot_score(
        citation_count,
        influential_citation_count,
        float(enriched.get("hot_score", 0) or 0),
        recency_score=recency_score,
    )
    quality_score = float(enriched.get("quality_score", 0) or 0)
    if not quality_score:
        quality_score = calculate_quality_score(str(enriched.get("title") or ""), abstract_en)
    overall_score = float(enriched.get("overall_score", 0) or 0)
    if not overall_score:
        overall_score = calculate_overall_score(
            relevance_score,
            hot_score,
            quality_score,
            recency_score,
        )

    enriched["abstract_en"] = abstract_en
    enriched["summary_cn"] = summary_cn
    enriched["one_liner_zh"] = one_liner_zh
    enriched["affiliations"] = affiliations
    enriched["author_meta"] = author_meta
    enriched["first_affiliation"] = first_affiliation
    enriched["code_urls"] = code_urls
    enriched["project_urls"] = project_urls
    enriched["citation_count"] = citation_count
    enriched["influential_citation_count"] = influential_citation_count
    enriched["hot_score"] = round(hot_score, 2)
    enriched["relevance_score"] = round(relevance_score, 2)
    enriched["recency_score"] = round(recency_score, 2)
    enriched["quality_score"] = round(quality_score, 2)
    enriched["overall_score"] = round(overall_score, 2)
    enriched["matched_domain"] = matched_domain
    enriched["matched_keywords"] = matched_keywords
    enriched["matched_excludes"] = matched_excludes
    enriched["context_hits"] = context_hits
    enriched["favorite_keywords"] = favorite_keywords
    enriched["favorite_ignores"] = favorite_ignores
    enriched["is_favorite"] = is_favorite
    enriched["is_ignored"] = is_ignored
    enriched["needs_agent_summary"] = not (one_liner_zh and summary_cn)
    enriched["needs_summary_cn_translation"] = not summary_cn
    enriched["needs_one_liner_zh"] = not one_liner_zh
    enriched["agent_translation_prompt"] = (
        build_agent_translation_prompt(str(enriched.get("title") or ""), abstract_en)
        if not summary_cn
        else ""
    )
    enriched["agent_one_liner_prompt"] = (
        build_agent_one_liner_prompt(str(enriched.get("title") or ""), abstract_en)
        if not one_liner_zh
        else ""
    )
    enriched["agent_summary_prompt"] = (
        (
            build_agent_translation_prompt(str(enriched.get("title") or ""), abstract_en)
            + "\n\n"
            + build_agent_one_liner_prompt(str(enriched.get("title") or ""), abstract_en)
        )
        if enriched["needs_agent_summary"]
        else ""
    )
    return enriched


def build_agent_completion_task(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "arxiv_id": str(entry.get("id") or ""),
        "title": str(entry.get("title") or ""),
        "needs_agent_summary": bool(entry.get("needs_agent_summary", False)),
        "needs_summary_cn_translation": bool(entry.get("needs_summary_cn_translation", False)),
        "needs_one_liner_zh": bool(entry.get("needs_one_liner_zh", False)),
        "agent_summary_prompt": str(entry.get("agent_summary_prompt") or ""),
        "agent_translation_prompt": str(entry.get("agent_translation_prompt") or ""),
        "agent_one_liner_prompt": str(entry.get("agent_one_liner_prompt") or ""),
        "expected_output_schema": {
            "arxiv_id": str(entry.get("id") or ""),
            "one_liner_zh": "string",
            "summary_cn": "string",
        },
    }


def build_agent_completion(tasks_source: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks = [build_agent_completion_task(entry) for entry in tasks_source if entry.get("needs_agent_summary")]
    return {
        "required": bool(tasks),
        "task_count": len(tasks),
        "recommended_batch_size": 3,
        "recommended_worker": "arxiv-enrich-agent-completion",
        "instructions": (
            "Use agent or subagent workers to fill one_liner_zh and summary_cn for each task. "
            "Preserve technical meaning, do not invent facts beyond the abstract, and return only structured fields."
        ),
        "tasks": tasks,
    }


def enrich_payload(
    payload: Dict[str, Any],
    *,
    enable_external_metadata: bool = False,
    semantic_scholar_api_key: Optional[str] = None,
    scoring_profile: Optional[Any] = None,
) -> Dict[str, Any]:
    enriched = dict(payload)
    mode = enriched.get("mode")

    if mode in {"daily", "search"}:
        enriched_entries = [
            enrich_entry(
                entry,
                enable_external_metadata=enable_external_metadata,
                semantic_scholar_api_key=semantic_scholar_api_key,
                scoring_profile=scoring_profile,
            )
            for entry in enriched.get("entries", [])
        ]
        enriched["entries"] = enriched_entries
        enriched["agent_completion"] = build_agent_completion(enriched_entries)
        return enriched

    if mode == "backfill":
        enriched_days = [
            enrich_payload(
                day,
                enable_external_metadata=enable_external_metadata,
                semantic_scholar_api_key=semantic_scholar_api_key,
                scoring_profile=scoring_profile,
            )
            for day in enriched.get("days", [])
        ]
        enriched["days"] = enriched_days
        day_tasks = [
            task
            for day in enriched_days
            for task in ((day.get("agent_completion") or {}).get("tasks") or [])
        ]
        enriched["agent_completion"] = {
            "required": bool(day_tasks),
            "task_count": len(day_tasks),
            "recommended_batch_size": 3,
            "recommended_worker": "arxiv-enrich-agent-completion",
            "instructions": (
                "Use agent or subagent workers to fill one_liner_zh and summary_cn for each task. "
                "Preserve technical meaning, do not invent facts beyond the abstract, and return only structured fields."
            ),
            "tasks": day_tasks,
        }
        return enriched

    raise ValueError(f"Unsupported payload mode: {mode}")


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-enrich")
    subparsers = parser.add_subparsers(dest="command")

    enrich = subparsers.add_parser("enrich")
    enrich.add_argument("--input")
    enrich.add_argument("--ids")
    enrich.add_argument("--ids-file")
    enrich.add_argument("--output", required=True)
    enrich.add_argument("--profile")
    enrich.add_argument("--semantic-scholar-api-key")
    enrich.add_argument("--enable-external-metadata", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "enrich":
        scoring_profile = load_scoring_profile(Path(args.profile)) if args.profile else None
        if args.input:
            payload = load_json(Path(args.input))
        elif args.ids:
            payload = build_payload_from_ids(split_ids(args.ids))
        elif args.ids_file:
            ids = split_ids(Path(args.ids_file).read_text(encoding="utf-8"))
            payload = build_payload_from_ids(ids)
        else:
            raise SystemExit("One of --input, --ids, or --ids-file is required")
        enriched = enrich_payload(
            payload,
            enable_external_metadata=args.enable_external_metadata,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            scoring_profile=scoring_profile,
        )
        save_json(Path(args.output), enriched)
        agent_completion = enriched.get("agent_completion") or {}
        print(
            json.dumps(
                {
                    "mode": enriched.get("mode"),
                    "output": str(args.output),
                    "agent_completion_required": bool(agent_completion.get("required", False)),
                    "agent_completion_task_count": int(agent_completion.get("task_count", 0) or 0),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
