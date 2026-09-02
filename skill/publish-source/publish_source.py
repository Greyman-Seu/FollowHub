#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SYNC_SCRIPT = REPO_ROOT / "skill" / "wiki-sync-page" / "wiki_sync_page.py"
MD_PREVIEW_SCRIPT = REPO_ROOT / "skill" / "md-preview" / "scripts" / "md_preview.py"
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
            request = Request(url, headers={"User-Agent": "followhub-publish-source/1.0"})
            with urlopen(request, timeout=20) as response:  # nosec - configured public URL
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise SystemExit(f"public page verification failed after {timeout_seconds}s: {url} ({last_error})")


def parse_key_value_lines(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish one wiki source note to R2.")
    parser.add_argument("--slug", required=True, help="Source slug")
    parser.add_argument("--wiki-root", required=True, help="llm-wiki root path")
    parser.add_argument("--page-root", required=True, help="page_github root path")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"), help="FollowHub config path")
    parser.add_argument("--remote-prefix", default="wiki", help="Remote R2 prefix")
    parser.add_argument("--site-base-url", default="https://tenstep.top", help="Public Page site base URL")
    parser.add_argument("--verify-timeout", type=int, default=360, help="Seconds to wait for the public Page URL")
    parser.add_argument("--no-page-push", action="store_true", help="Skip page_github commit and push")
    parser.add_argument("--no-page-verify", action="store_true", help="Skip public Page URL verification")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    page_root = Path(args.page_root).expanduser().resolve()
    source_md = wiki_root / "wiki" / "sources" / f"{args.slug}.md"
    if not source_md.is_file():
        raise SystemExit(f"source markdown not found: {source_md}")

    sync_proc = run([
        sys.executable,
        str(WIKI_SYNC_SCRIPT),
        "sync",
        "--wiki-root",
        str(wiki_root),
        "--page-root",
        str(page_root),
        "--slug",
        args.slug,
    ])
    if sync_proc.returncode != 0:
        raise SystemExit(sync_proc.stderr or sync_proc.stdout)

    with tempfile.TemporaryDirectory(prefix="publish-source-") as tmpdir:
        render_proc = run([
            sys.executable,
            str(MD_PREVIEW_SCRIPT),
            "render",
            "--input",
            str(source_md),
            "--output-dir",
            tmpdir,
        ])
        if render_proc.returncode != 0:
            raise SystemExit(render_proc.stderr or render_proc.stdout)
        rendered = parse_key_value_lines(render_proc.stdout)
        html_path = Path(rendered["html_path"]).resolve()
        source_json = page_root / "src" / "data" / "generated" / "wiki-sync" / "source" / f"{args.slug}.json"
        if not source_json.is_file():
            raise SystemExit(f"source json not found: {source_json}")

        html_key = f"{args.remote_prefix}/source/{args.slug}.html"
        json_key = f"{args.remote_prefix}/source/{args.slug}.json"

        html_upload = run([
            sys.executable,
            str(RCLI_SCRIPT),
            "--config-file",
            args.config,
            "--json",
            "copyto",
            str(html_path),
            html_key,
        ])
        if html_upload.returncode != 0:
            raise SystemExit(html_upload.stderr or html_upload.stdout)
        json_upload = run([
            sys.executable,
            str(RCLI_SCRIPT),
            "--config-file",
            args.config,
            "--json",
            "copyto",
            str(source_json),
            json_key,
        ])
        if json_upload.returncode != 0:
            raise SystemExit(json_upload.stderr or json_upload.stdout)

        html_payload = json.loads(html_upload.stdout)
        json_payload = json.loads(json_upload.stdout)
        if not args.no_page_push:
            publish_page_repo(page_root, f"Publish source {args.slug}")
        public_page_url = f"{args.site_base_url.rstrip('/')}/wiki/source/{args.slug}"
        if not args.no_page_verify:
            wait_for_public_url(public_page_url, args.verify_timeout)
        print(json.dumps({
            "ok": True,
            "slug": args.slug,
            "html_url": html_payload.get("url"),
            "json_url": json_payload.get("url"),
            "public_page_url": public_page_url,
            "source_md": str(source_md),
            "source_json": str(source_json),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
