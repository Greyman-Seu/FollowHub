#!/usr/bin/env python3
"""Package RSS digests into canonical Follow output artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict
import subprocess
import sys


HELP_TEXT = """\
rss-publish: Package RSS daily digests via follow-publish.

Usage:
    rss-publish help
    rss-publish build-daily --input rss-daily-output/2026-05-12/daily-digest.json --output-dir rss-daily-output/2026-05-12/publish-out
"""


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(REPO_ROOT), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"Command failed: {' '.join(args)}\n{detail}")
    return proc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-publish")
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build-daily")
    build.add_argument("--input", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--date")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if not argv:
        argv = sys.argv[1:]
    if not argv or argv[0] == "help":
        print(HELP_TEXT)
        return 0
    args = build_parser().parse_args(argv)
    if args.command == "build-daily":
        digest = load_json(Path(args.input))
        digest_date = args.date or str(digest.get("date") or "")
        digest_path = Path(args.input)
        payload = dict(digest)
        payload["date"] = digest_date
        digest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        proc = run_command(
            [
                sys.executable,
                str(REPO_ROOT / "skill" / "follow-publish" / "follow_publish.py"),
                "build-daily",
                "--input",
                str(digest_path),
                "--output-dir",
                str(Path(args.output_dir)),
            ]
        )
        stdout = (proc.stdout or "").strip()
        print(stdout if stdout else json.dumps({"mode": "rss-publish", "output_dir": args.output_dir}, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
