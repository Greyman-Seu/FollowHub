#!/usr/bin/env python3
"""Install the FollowHub daily user service and timer."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


UNIT_NAME = "followhub-daily"
RUN_HOURS = (7, 9, 11, 13, 15, 17, 19, 21, 23)


def _unit_value(value: Path) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("unit paths must not contain newlines")
    return text.replace("%", "%%")


def build_service_unit(repo: Path, codex_bin: Path, config_path: Path) -> str:
    runner = repo / "skill" / "daily" / "scripts" / "run_scheduled_daily.py"
    return """[Unit]
Description=Run FollowHub daily production update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={repo}
Environment="TZ=Asia/Shanghai"
Environment="FOLLOWHUB_CONFIG={config}"
ExecStart=/usr/bin/python3 {runner} --repo {repo} --config {config} --codex-bin {codex}
TimeoutStartSec=1h50min
Nice=5
""".format(
        repo=_unit_value(repo),
        config=_unit_value(config_path),
        runner=_unit_value(runner),
        codex=_unit_value(codex_bin),
    )


def build_timer_unit() -> str:
    calendar_lines = "\n".join(
        "OnCalendar=*-*-* {0:02d}:00:00 Asia/Shanghai".format(hour)
        for hour in RUN_HOURS
    )
    return """[Unit]
Description=Check FollowHub daily every two hours from 07:00

[Timer]
{calendar_lines}
Persistent=true
AccuracySec=1min
Unit={unit}.service

[Install]
WantedBy=timers.target
""".format(calendar_lines=calendar_lines, unit=UNIT_NAME)


def write_unit(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_systemctl(args: List[str]) -> None:
    subprocess.run(["systemctl", "--user"] + args, check=True)


def install(
    *, repo: Path, codex_bin: Path, config_path: Path, enable: bool = True
) -> Dict[str, str]:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    service_path = unit_dir / "{0}.service".format(UNIT_NAME)
    timer_path = unit_dir / "{0}.timer".format(UNIT_NAME)
    write_unit(service_path, build_service_unit(repo, codex_bin, config_path))
    write_unit(timer_path, build_timer_unit())
    run_systemctl(["daemon-reload"])
    if enable:
        run_systemctl(["enable", "--now", "{0}.timer".format(UNIT_NAME)])
    return {"service": str(service_path), "timer": str(timer_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="install-followhub-scheduled-daily")
    parser.add_argument("--repo")
    parser.add_argument("--config")
    parser.add_argument("--codex-bin")
    parser.add_argument("--no-enable", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    inferred_repo = Path(__file__).resolve().parents[3]
    repo = Path(args.repo or inferred_repo).expanduser().resolve()
    config_path = Path(args.config or repo / "followhub.yaml").expanduser().resolve()
    codex_value = args.codex_bin or shutil.which("codex")
    if not codex_value:
        raise SystemExit("codex executable not found")
    codex_bin = Path(codex_value).expanduser().resolve()
    if not config_path.exists():
        raise SystemExit("FollowHub config not found: {0}".format(config_path))
    paths = install(
        repo=repo,
        codex_bin=codex_bin,
        config_path=config_path,
        enable=not args.no_enable,
    )
    print(
        json.dumps(
            {
                "installed": paths,
                "enabled": not args.no_enable,
                "hours": list(RUN_HOURS),
                "timezone": "Asia/Shanghai",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
