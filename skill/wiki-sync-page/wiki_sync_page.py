#!/usr/bin/env python3
"""
wiki_sync_page.py - Inspect and stage public llm-wiki content for website sync.
"""

from __future__ import annotations

import argparse
import json
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
    print(f"manifest_path={manifest_path}")
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

