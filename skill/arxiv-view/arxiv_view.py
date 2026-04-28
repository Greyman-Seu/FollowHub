#!/usr/bin/env python3
"""
arxiv_view.py - Static viewer builder for arxiv-find outputs.
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


HELP_TEXT = """\
arxiv-view: Build a static viewer bundle from arxiv-find outputs.

Usage:
    arxiv-view help
    arxiv-view build --input /path/to/arxiv-find-output --output-dir ./arxiv-view-out
"""


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_input(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")

    if path.suffix.lower() == ".json":
        payload = load_json(path)
        if payload.get("mode") == "daily":
            return {"kind": "daily", "payload": payload, "path": path}
        if payload.get("mode") == "search":
            return {"kind": "search", "payload": payload, "path": path}
        if payload.get("result", {}).get("mode") == "backfill":
            daily_files = [
                Path(item["output_json"])
                for item in payload.get("written", {}).get("daily_runs", [])
            ]
            return {
                "kind": "backfill",
                "payload": payload["result"],
                "path": path,
                "daily_files": daily_files,
                "overview_path": Path(payload.get("written", {}).get("overview_markdown", "")),
            }
        raise ValueError(f"Unsupported JSON input shape: {path}")

    if path.suffix.lower() == ".md":
        text = path.read_text(encoding="utf-8")
        if "Backfill Overview" not in text:
            raise ValueError(f"Unsupported markdown input: {path}")
        daily_files = parse_backfill_overview_markdown(text, path.parent)
        return {
            "kind": "backfill",
            "payload": {
                "mode": "backfill",
                "date_from": parse_backfill_range(text)[0],
                "date_to": parse_backfill_range(text)[1],
            },
            "path": path,
            "daily_files": daily_files,
            "overview_path": path,
        }

    raise ValueError(f"Unsupported input file type: {path}")


def parse_backfill_range(text: str) -> List[str]:
    match = re.search(r"- Date range:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*->\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    if match:
        return [match.group(1), match.group(2)]
    return ["", ""]


def parse_backfill_overview_markdown(text: str, base_dir: Path) -> List[Path]:
    daily_files: List[Path] = []
    for raw_path in re.findall(r"->\s*(.+?\.md)\s*$", text, flags=re.MULTILINE):
        markdown_path = Path(raw_path.strip())
        if not markdown_path.is_absolute():
            markdown_path = (base_dir / markdown_path).resolve()
        json_path = markdown_path.with_suffix(".json")
        daily_files.append(json_path)
    if not daily_files:
        raise ValueError("Backfill overview did not reference any daily output files")
    return daily_files


def normalize_entry(entry: Dict[str, Any], *, source_mode: str, source_day: str = "") -> Dict[str, Any]:
    affiliations = list(entry.get("affiliations") or [])
    first_affiliation = entry.get("first_affiliation") or (affiliations[0] if affiliations else "")
    return {
        "arxiv_id": entry.get("id") or entry.get("arxiv_id") or "",
        "title": entry.get("title") or "",
        "one_liner_zh": entry.get("one_liner_zh") or "",
        "summary_cn": entry.get("summary_cn") or entry.get("digest_zh") or "",
        "abstract_en": entry.get("abstract_en") or entry.get("summary") or entry.get("abstract") or "",
        "authors": list(entry.get("authors") or []),
        "first_affiliation": first_affiliation,
        "affiliations": affiliations,
        "categories": list(entry.get("categories") or []),
        "published": entry.get("published") or "",
        "updated": entry.get("updated") or "",
        "pdf_url": entry.get("pdf_url") or "",
        "html_url": entry.get("html_url") or "",
        "code_urls": list(entry.get("code_urls") or []),
        "project_urls": list(entry.get("project_urls") or []),
        "citation_count": entry.get("citation_count", 0) or 0,
        "influential_citation_count": entry.get("influential_citation_count", 0) or 0,
        "hot_score": entry.get("hot_score", 0) or 0,
        "relevance_score": entry.get("relevance_score", 0),
        "quality_score": entry.get("quality_score", 0) or 0,
        "overall_score": entry.get("overall_score", 0) or 0,
        "matched_keywords": list(entry.get("matched_keywords") or []),
        "favorite_default": False,
        "favorite_keywords": list(entry.get("favorite_keywords") or []),
        "context_hits": list(entry.get("context_hits") or []),
        "source_day": source_day,
        "source_mode": source_mode,
    }


def normalize_daily(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = [
        normalize_entry(item, source_mode="daily", source_day=payload.get("date", ""))
        for item in payload.get("entries", [])
    ]
    return {
        "mode": "daily",
        "title": f"arXiv Daily Brief - {payload.get('date', '')}",
        "subtitle": f"{payload.get('count', len(items))} paper(s) from {payload.get('source', 'daily')}",
        "items": items,
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "day_count": 1,
            "item_count": len(items),
            "days": [payload.get("date", "")] if payload.get("date") else [],
            "categories": sorted({cat for item in items for cat in item["categories"]}),
        },
    }


def normalize_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = [
        normalize_entry(item, source_mode="search")
        for item in payload.get("entries", [])
    ]
    return {
        "mode": "search",
        "title": "arXiv Search Results",
        "subtitle": f"{payload.get('count', len(items))} paper(s)",
        "items": items,
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "item_count": len(items),
            "day_count": 0,
            "days": [],
            "query": payload.get("query", ""),
            "categories": sorted({cat for item in items for cat in item["categories"]}),
        },
    }


def normalize_backfill(daily_payloads: Sequence[Dict[str, Any]], *, date_from: str = "", date_to: str = "") -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    days: List[str] = []
    for payload in daily_payloads:
        source_day = payload.get("date", "")
        if source_day:
            days.append(source_day)
        items.extend(
            normalize_entry(item, source_mode="daily", source_day=source_day)
            for item in payload.get("entries", [])
        )
    items.sort(key=lambda item: (item["source_day"], item["published"], item["title"]), reverse=True)
    return {
        "mode": "backfill",
        "title": "arXiv Backfill Overview",
        "subtitle": f"{len(days)} day(s), {len(items)} paper(s)",
        "items": items,
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "item_count": len(items),
            "day_count": len(days),
            "days": sorted(days),
            "date_from": date_from,
            "date_to": date_to,
            "categories": sorted({cat for item in items for cat in item["categories"]}),
        },
    }


def normalize_loaded_input(loaded: Dict[str, Any]) -> Dict[str, Any]:
    kind = loaded["kind"]
    if kind == "daily":
        return normalize_daily(loaded["payload"])
    if kind == "search":
        return normalize_search(loaded["payload"])
    if kind == "backfill":
        daily_payloads = [load_json(path) for path in loaded["daily_files"]]
        date_from = loaded.get("payload", {}).get("date_from", "")
        date_to = loaded.get("payload", {}).get("date_to", "")
        return normalize_backfill(daily_payloads, date_from=date_from, date_to=date_to)
    raise ValueError(f"Unsupported input kind: {kind}")


def build_bundle(*, input_path: Path, output_dir: Path) -> Dict[str, Any]:
    loaded = load_input(Path(input_path))
    normalized = normalize_loaded_input(loaded)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).resolve().parent / "view_template"
    shutil.copy2(template_dir / "index.html", output_dir / "index.html")
    shutil.copy2(template_dir / "app.js", output_dir / "app.js")
    shutil.copy2(template_dir / "styles.css", output_dir / "styles.css")

    with open(output_dir / "data.json", "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)

    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-view")
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser("build")
    build.add_argument("--input", required=True)
    build.add_argument("--output-dir", required=True)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        normalized = build_bundle(
            input_path=Path(args.input),
            output_dir=Path(args.output_dir),
        )
        print(json.dumps({"mode": normalized["mode"], "item_count": len(normalized["items"])}, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
