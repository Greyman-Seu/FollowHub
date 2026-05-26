#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SYNC_SCRIPT = REPO_ROOT / "skill" / "wiki-sync-page" / "wiki_sync_page.py"
RCLI_SCRIPT = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish full wiki structured data to R2.")
    parser.add_argument("--wiki-root", required=True, help="llm-wiki root path")
    parser.add_argument("--page-root", required=True, help="page_github root path")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"), help="FollowHub config path")
    parser.add_argument("--remote-prefix", default="wiki", help="Remote R2 prefix")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    page_root = Path(args.page_root).expanduser().resolve()

    sync_proc = run([
        sys.executable,
        str(WIKI_SYNC_SCRIPT),
        "sync",
        "--wiki-root",
        str(wiki_root),
        "--page-root",
        str(page_root),
    ])
    if sync_proc.returncode != 0:
        raise SystemExit(sync_proc.stderr or sync_proc.stdout)

    generated_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    graph_data = wiki_root / "wiki" / "graph-data.json"
    graph_html = wiki_root / "wiki" / "knowledge-graph.html"

    with tempfile.TemporaryDirectory(prefix="publish-wiki-") as tmpdir:
      stage = Path(tmpdir) / "wiki"
      shutil.copytree(generated_dir, stage / "data")
      if graph_data.is_file():
          (stage / "graph").mkdir(parents=True, exist_ok=True)
          shutil.copy2(graph_data, stage / "graph" / "graph-data.json")
      if graph_html.is_file():
          (stage / "graph").mkdir(parents=True, exist_ok=True)
          shutil.copy2(graph_html, stage / "graph" / "knowledge-graph.html")
      upload = run([
          sys.executable,
          str(RCLI_SCRIPT),
          "--config-file",
          args.config,
          "--json",
          "sync",
          str(stage),
          args.remote_prefix,
      ])
      if upload.returncode != 0:
          raise SystemExit(upload.stderr or upload.stdout)
      payload = json.loads(upload.stdout)
      print(json.dumps({
          "ok": True,
          "remote_prefix": args.remote_prefix,
          "url": payload.get("url"),
          "generated_dir": str(generated_dir),
          "graph_data": str(graph_data) if graph_data.is_file() else "",
          "graph_html": str(graph_html) if graph_html.is_file() else "",
      }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
