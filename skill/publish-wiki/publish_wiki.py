#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SYNC_SCRIPT = REPO_ROOT / "skill" / "wiki-sync-page" / "wiki_sync_page.py"
RCLI_SCRIPT = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def git_run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args])


def publish_page_repo(page_root: Path, commit_message: str) -> str:
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
    head_proc = git_run(page_root, "rev-parse", "HEAD")
    if head_proc.returncode != 0:
        raise SystemExit(head_proc.stderr or head_proc.stdout)
    return head_proc.stdout.strip()


def resolve_github_pages_workflow(page_root: Path) -> tuple[str, str] | None:
    remote_proc = git_run(page_root, "remote", "get-url", "origin")
    if remote_proc.returncode != 0:
        return None
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", remote_proc.stdout.strip())
    if not match:
        return None
    workflow_dir = page_root / ".github" / "workflows"
    for workflow_path in sorted(workflow_dir.glob("*.y*ml")):
        if "deploy-pages" in workflow_path.read_text(encoding="utf-8"):
            return match.group(1), workflow_path.name
    return None


def wait_for_page_deployment(page_root: Path, commit_sha: str, timeout_seconds: int) -> None:
    resolved = resolve_github_pages_workflow(page_root)
    if not resolved:
        return
    repo, workflow = resolved
    workflow_url = f"https://github.com/{repo}/actions/workflows/{workflow}"
    commit_marker = f"/{repo}/commit/{commit_sha}"
    deadline = time.monotonic() + timeout_seconds
    last_error = "workflow run not found"
    while time.monotonic() < deadline:
        try:
            request = Request(workflow_url, headers={"User-Agent": "followhub-publish-wiki/1.0"})
            with urlopen(request, timeout=20) as response:  # nosec - derived public GitHub URL
                html = response.read().decode("utf-8", errors="replace")
            marker_index = html.find(commit_marker)
            if marker_index >= 0:
                run_context = html[max(0, marker_index - 4000):marker_index]
                if "completed successfully:" in run_context:
                    return
                if "completed with failure:" in run_context or "completed with cancellation:" in run_context:
                    raise SystemExit(f"GitHub Pages deployment failed for {commit_sha}: {workflow_url}")
                last_error = "workflow run is still queued or running"
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise SystemExit(f"GitHub Pages deployment did not complete after {timeout_seconds}s: {workflow_url} ({last_error})")


def wait_for_public_url(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    current_url = url
    while time.monotonic() < deadline:
        try:
            request = Request(current_url, headers={"User-Agent": "followhub-publish-wiki/1.0"})
            with urlopen(request, timeout=20) as response:  # nosec - configured public URL
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in {301, 302, 303, 307, 308} and location:
                current_url = urljoin(current_url, location)
                continue
            last_error = str(exc)
        except (URLError, TimeoutError) as exc:
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
          commit_sha = publish_page_repo(page_root, "Update wiki sync data")
          if not args.no_page_verify:
              wait_for_page_deployment(page_root, commit_sha, args.verify_timeout)
      public_page_url = f"{args.site_base_url.rstrip('/')}/wiki"
      verify_slug = args.verify_slug or args.slug
      if verify_slug:
          public_page_url = f"{public_page_url}/source/{verify_slug}"
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
