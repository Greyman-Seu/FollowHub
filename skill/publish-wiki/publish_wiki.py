#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SYNC_SCRIPT = REPO_ROOT / "skill" / "wiki-sync-page" / "wiki_sync_page.py"
RCLI_SCRIPT = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def git_run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args])


def publish_page_repo(page_root: Path, commit_message: str) -> None:
    generated_path = "src/data/generated/wiki-sync"
    status_proc = git_run(page_root, "status", "--short", "--", generated_path)
    if status_proc.returncode != 0:
        raise SystemExit(status_proc.stderr or status_proc.stdout)
    if status_proc.stdout.strip():
        add_proc = git_run(page_root, "add", generated_path)
        if add_proc.returncode != 0:
            raise SystemExit(add_proc.stderr or add_proc.stdout)
        commit_proc = git_run(page_root, "commit", "-m", commit_message)
        if commit_proc.returncode != 0:
            raise SystemExit(commit_proc.stderr or commit_proc.stdout)
    push_proc = git_run(page_root, "push", "origin", "main")
    if push_proc.returncode != 0:
        raise SystemExit(push_proc.stderr or push_proc.stdout)


def wait_for_public_url(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = Request(url, headers={"User-Agent": "followhub-publish-wiki/1.0"})
            with urlopen(request, timeout=20) as response:  # nosec - configured public URL
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise SystemExit(f"public page verification failed after {timeout_seconds}s: {url} ({last_error})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish full wiki structured data to R2.")
    parser.add_argument("--wiki-root", required=True, help="llm-wiki root path")
    parser.add_argument("--page-root", required=True, help="page_github root path")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"), help="FollowHub config path")
    parser.add_argument("--remote-prefix", default="wiki", help="Remote R2 prefix")
    parser.add_argument("--slug", help="Optional source slug for single-page sync and verification")
    parser.add_argument("--site-base-url", default="https://tenstep.top", help="Public Page site base URL")
    parser.add_argument("--verify-slug", help="Source slug to verify after the Page deployment")
    parser.add_argument("--verify-timeout", type=int, default=360, help="Seconds to wait for the public Page URL")
    parser.add_argument("--no-page-push", action="store_true", help="Skip page_github commit and push")
    parser.add_argument("--no-page-verify", action="store_true", help="Skip public Page URL verification")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    page_root = Path(args.page_root).expanduser().resolve()
    sync_args = [
        sys.executable,
        str(WIKI_SYNC_SCRIPT),
        "sync",
        "--wiki-root",
        str(wiki_root),
        "--page-root",
        str(page_root),
    ]
    if args.slug:
        sync_args.extend(["--slug", args.slug])

    sync_proc = run(sync_args)
    if sync_proc.returncode != 0:
        raise SystemExit(sync_proc.stderr or sync_proc.stdout)

    generated_dir = page_root / "src" / "data" / "generated" / "wiki-sync"
    graph_data = wiki_root / "wiki" / "graph-data.json"
    graph_html = wiki_root / "wiki" / "knowledge-graph.html"

    with tempfile.TemporaryDirectory(prefix="publish-wiki-") as tmpdir:
      stage = Path(tmpdir) / "wiki"
      shutil.copytree(generated_dir, stage)
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
      if not args.no_page_push:
          publish_page_repo(page_root, "Update wiki sync data")
      public_page_url = f"{args.site_base_url.rstrip('/')}/wiki"
      if args.verify_slug:
          public_page_url = f"{public_page_url}/source/{args.verify_slug}"
      if not args.no_page_verify:
          wait_for_public_url(public_page_url, args.verify_timeout)
      print(json.dumps({
          "ok": True,
          "remote_prefix": args.remote_prefix,
          "url": payload.get("url"),
          "public_page_url": public_page_url,
          "generated_dir": str(generated_dir),
          "graph_data": str(graph_data) if graph_data.is_file() else "",
          "graph_html": str(graph_html) if graph_html.is_file() else "",
      }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
