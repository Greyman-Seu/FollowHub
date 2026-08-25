#!/usr/bin/env python3
"""Run FollowHub daily from a systemd timer until the current day succeeds."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from check_daily_success import check_daily_success


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(str(temporary), str(path))


def default_run_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def build_prompt(prompt_path: Path, run_date: str) -> str:
    body = prompt_path.read_text(encoding="utf-8").strip()
    return (
        "本次自动化运行日期是 {0}（Asia/Shanghai）。\n"
        "只处理这个日期，并严格执行下面的生产任务。\n\n{1}\n"
    ).format(run_date, body)


def build_codex_command(
    *, codex_bin: str, repo: Path, output_message_path: Path
) -> List[str]:
    return [
        codex_bin,
        "exec",
        "--ephemeral",
        "--color",
        "never",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(repo),
        "-o",
        str(output_message_path),
        "-",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-followhub-scheduled-daily")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config")
    parser.add_argument("--prompt")
    parser.add_argument("--codex-bin")
    parser.add_argument("--state-dir")
    parser.add_argument("--date")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    config_path = Path(args.config or repo / "followhub.yaml").expanduser().resolve()
    prompt_path = Path(
        args.prompt or repo / "skill" / "daily" / "automation_prompt.md"
    ).expanduser().resolve()
    state_dir = Path(
        args.state_dir
        or Path.home() / ".local" / "state" / "followhub-daily"
    ).expanduser().resolve()
    run_date = args.date or default_run_date()
    codex_bin = args.codex_bin or shutil.which("codex")
    if not codex_bin:
        raise SystemExit("codex executable not found")
    if not config_path.exists():
        raise SystemExit("FollowHub config not found: {0}".format(config_path))
    if not prompt_path.exists():
        raise SystemExit("automation prompt not found: {0}".format(prompt_path))

    state_dir.mkdir(parents=True, exist_ok=True)
    success_path = state_dir / "{0}.success.json".format(run_date)
    attempt_path = state_dir / "{0}.last-attempt.json".format(run_date)
    output_message_path = state_dir / "{0}.last-message.txt".format(run_date)
    lock_path = state_dir / "{0}.lock".format(run_date)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("FollowHub daily is already running for {0}; skipping.".format(run_date))
            return 0

        if success_path.exists():
            print("FollowHub daily already succeeded for {0}; skipping.".format(run_date))
            return 0

        precheck = check_daily_success(repo, run_date, config_path)
        if precheck.get("ok"):
            precheck["detected_at"] = datetime.now().astimezone().isoformat()
            precheck["source"] = "preflight"
            write_json_atomic(success_path, precheck)
            print("Existing successful daily detected for {0}; marker written.".format(run_date))
            return 0

        started_at = datetime.now().astimezone().isoformat()
        environment = os.environ.copy()
        environment["FOLLOWHUB_CONFIG"] = str(config_path)
        command = build_codex_command(
            codex_bin=codex_bin,
            repo=repo,
            output_message_path=output_message_path,
        )
        proc = subprocess.run(
            command,
            input=build_prompt(prompt_path, run_date),
            text=True,
            cwd=str(repo),
            env=environment,
            check=False,
        )
        postcheck = check_daily_success(repo, run_date, config_path)
        finished_at = datetime.now().astimezone().isoformat()
        attempt = {
            "date": run_date,
            "started_at": started_at,
            "finished_at": finished_at,
            "codex_returncode": proc.returncode,
            "precheck": precheck,
            "postcheck": postcheck,
        }
        write_json_atomic(attempt_path, attempt)
        if postcheck.get("ok"):
            success = dict(postcheck)
            success.update(
                {
                    "detected_at": finished_at,
                    "source": "scheduled-run",
                    "codex_returncode": proc.returncode,
                }
            )
            write_json_atomic(success_path, success)
            print("FollowHub daily succeeded for {0}.".format(run_date))
            return 0

        print(
            "FollowHub daily is still pending for {0}: {1}".format(
                run_date, postcheck.get("reason", "unknown verification failure")
            ),
            file=sys.stderr,
        )
        return proc.returncode if proc.returncode else 1


if __name__ == "__main__":
    raise SystemExit(main())
