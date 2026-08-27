#!/usr/bin/env python3
"""Install the FollowHub daily user service and timer."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


UNIT_NAME = "followhub-daily"
RUN_HOURS = (7, 9, 11, 13, 15, 17, 19, 21, 23)
SYSTEM_PATH = (
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:"
    "/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"
)
LARK_CHANNEL_ENVIRONMENT = (
    "LARK_CHANNEL",
    "LARK_CHANNEL_HOME",
    "LARK_CHANNEL_PROFILE",
    "LARK_CHANNEL_CONFIG",
    "LARKSUITE_CLI_CONFIG_DIR",
)


def _unit_value(value: object) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("unit paths must not contain newlines")
    return text.replace("%", "%%")


def _repeatable_cli_arguments(flag: str, values: Optional[List[str]]) -> str:
    parts: List[str] = []
    for value in values or []:
        text = str(value or "").strip().lower()
        if not text:
            continue
        parts.append(" {0} {1}".format(flag, _unit_value(text)))
    return "".join(parts)


def build_service_unit(
    repo: Path,
    codex_bin: Path,
    config_path: Path,
    *,
    node_bin: Optional[Path] = None,
    lark_cli: Optional[Path] = None,
    notify_chat_id: Optional[str] = None,
    summary_url: str = "https://tenstep.top/follow/",
    allow_unavailable_sources: Optional[List[str]] = None,
    notify_pending_once: bool = False,
    channel_environment: Optional[Dict[str, str]] = None,
) -> str:
    runner = repo / "skill" / "daily" / "scripts" / "run_scheduled_daily.py"
    environment_lines = []
    if node_bin is not None:
        environment_lines.append(
            'Environment="PATH={0}:{1}"'.format(
                _unit_value(node_bin.parent), SYSTEM_PATH
            )
        )
    for key, value in (channel_environment or {}).items():
        if key not in LARK_CHANNEL_ENVIRONMENT or not value:
            continue
        environment_lines.append(
            'Environment="{0}={1}"'.format(key, _unit_value(value))
        )
    notify_arguments = ""
    if notify_chat_id:
        if lark_cli is None:
            raise ValueError("lark-cli is required when notifications are enabled")
        notify_arguments = " --lark-cli {0} --notify-chat-id {1} --summary-url {2}".format(
            _unit_value(lark_cli),
            _unit_value(notify_chat_id),
            _unit_value(summary_url),
        )
    optional_source_arguments = _repeatable_cli_arguments(
        "--allow-unavailable-source",
        allow_unavailable_sources,
    )
    pending_argument = " --notify-pending-once" if notify_pending_once else ""
    return """[Unit]
Description=Run FollowHub daily production update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={repo}
Environment="TZ=Asia/Shanghai"
Environment="FOLLOWHUB_CONFIG={config}"
{channel_environment}
ExecStart=/usr/bin/python3 {runner} --repo {repo} --config {config} --codex-bin {codex}{notify_arguments}{optional_source_arguments}{pending_argument}
TimeoutStartSec=1h50min
Nice=5
""".format(
        repo=_unit_value(repo),
        config=_unit_value(config_path),
        runner=_unit_value(runner),
        codex=_unit_value(codex_bin),
        notify_arguments=notify_arguments,
        optional_source_arguments=optional_source_arguments,
        pending_argument=pending_argument,
        channel_environment="\n".join(environment_lines),
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
    *,
    repo: Path,
    codex_bin: Path,
    config_path: Path,
    node_bin: Optional[Path] = None,
    lark_cli: Optional[Path] = None,
    notify_chat_id: Optional[str] = None,
    summary_url: str = "https://tenstep.top/follow/",
    allow_unavailable_sources: Optional[List[str]] = None,
    notify_pending_once: bool = False,
    channel_environment: Optional[Dict[str, str]] = None,
    enable: bool = True,
) -> Dict[str, str]:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    service_path = unit_dir / "{0}.service".format(UNIT_NAME)
    timer_path = unit_dir / "{0}.timer".format(UNIT_NAME)
    write_unit(
        service_path,
        build_service_unit(
            repo,
            codex_bin,
            config_path,
            node_bin=node_bin,
            lark_cli=lark_cli,
            notify_chat_id=notify_chat_id,
            summary_url=summary_url,
            allow_unavailable_sources=allow_unavailable_sources,
            notify_pending_once=notify_pending_once,
            channel_environment=channel_environment,
        ),
    )
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
    parser.add_argument("--node-bin")
    parser.add_argument("--lark-cli")
    parser.add_argument("--notify-chat-id")
    parser.add_argument("--summary-url", default="https://tenstep.top/follow/")
    parser.add_argument("--allow-unavailable-source", action="append", default=[])
    parser.add_argument("--notify-pending-once", action="store_true")
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
    node_value = args.node_bin or shutil.which("node")
    if not node_value:
        raise SystemExit("node executable not found")
    node_bin = Path(node_value).expanduser().resolve()
    lark_value = args.lark_cli or shutil.which("lark-cli")
    if args.notify_chat_id and not lark_value:
        raise SystemExit("lark-cli executable not found")
    lark_cli = Path(lark_value).expanduser().resolve() if lark_value else None
    if not config_path.exists():
        raise SystemExit("FollowHub config not found: {0}".format(config_path))
    paths = install(
        repo=repo,
        codex_bin=codex_bin,
        config_path=config_path,
        node_bin=node_bin,
        lark_cli=lark_cli,
        notify_chat_id=args.notify_chat_id,
        summary_url=args.summary_url,
        allow_unavailable_sources=args.allow_unavailable_source,
        notify_pending_once=bool(args.notify_pending_once),
        channel_environment={
            key: os.environ[key]
            for key in LARK_CHANNEL_ENVIRONMENT
            if os.environ.get(key)
        },
        enable=not args.no_enable,
    )
    print(
        json.dumps(
            {
                "installed": paths,
                "enabled": not args.no_enable,
                "hours": list(RUN_HOURS),
                "timezone": "Asia/Shanghai",
                "node_bin": str(node_bin),
                "notifications": bool(args.notify_chat_id),
                "summary_url": args.summary_url if args.notify_chat_id else None,
                "allow_unavailable_sources": list(args.allow_unavailable_source or []),
                "notify_pending_once": bool(args.notify_pending_once),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
