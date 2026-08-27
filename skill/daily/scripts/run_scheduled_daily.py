#!/usr/bin/env python3
"""Run FollowHub daily from a systemd timer until the current day succeeds."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from check_daily_success import check_daily_success


SUCCESS_SCHEMA_VERSION = 2
DEFAULT_FINAL_RETRY_HOUR = 23
SOURCE_LABELS = {
    "arxiv": "arXiv",
    "wechat": "微信",
    "x": "X/Twitter",
    "bilibili": "B站",
}


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(str(temporary), str(path))


def default_run_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def normalize_source_names(values: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for value in values or []:
        source = str(value or "").strip().lower()
        if not source or source in seen:
            continue
        seen.add(source)
        normalized.append(source)
    return normalized


def build_prompt(
    prompt_path: Path,
    run_date: str,
    *,
    allow_unavailable_sources: Optional[List[str]] = None,
) -> str:
    body = prompt_path.read_text(encoding="utf-8").strip()
    optional_sources = normalize_source_names(allow_unavailable_sources)
    override = ""
    if optional_sources:
        labels = "、".join(SOURCE_LABELS.get(source, source) for source in optional_sources)
        override = (
            "\n安装级覆盖：以下 source family 即使全部采集失败，也不阻塞当天完成：{0}。\n"
            "对这些 source family，仍要诚实记录 outage，并继续完成其他已验证来源的 digest、publish、verify 与通知。\n"
        ).format(labels)
    return (
        "本次自动化运行日期是 {0}（Asia/Shanghai）。\n"
        "只处理这个日期，并严格执行下面的生产任务。\n\n{1}\n"
        "{2}"
    ).format(run_date, body, override)


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


def load_json_optional(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _count_summary(result: Dict[str, Any]) -> str:
    counts = result.get("counts") or {}
    parts = [
        "{0} {1}".format(SOURCE_LABELS[source], int(counts.get(source, 0) or 0))
        for source in SOURCE_LABELS
    ]
    return "，".join(parts)


def _x_health_summary(result: Dict[str, Any]) -> str:
    health = (result.get("collection_health") or {}).get("x") or {}
    total = int(health.get("total", 0) or 0)
    if total <= 0:
        return ""
    ok = int(health.get("ok", 0) or 0)
    errors = int(health.get("error", 0) or 0)
    error_kinds = health.get("error_kinds") or {}
    details = []
    for key, label in (("dns", "DNS"), ("timeout", "超时"), ("forbidden", "403"), ("other", "其他")):
        count = int(error_kinds.get(key, 0) or 0)
        if count:
            details.append("{0} {1}".format(label, count))
    suffix = "（{0}）".format("、".join(details)) if details else ""
    ignored = "x" in set(result.get("ignored_unavailable_sources") or [])
    note = "；按配置已忽略，不阻塞本次发布" if ignored and ok == 0 else ""
    return "X/Twitter RSS：{0}/{1} 个源可用，{2} 个失败{3}".format(
        ok, total, errors, suffix
    ) + note


def _wechat_health_summary(result: Dict[str, Any]) -> str:
    health = (result.get("fetch_health") or {}).get("wechat") or {}
    item_count = int(health.get("item_count", 0) or 0)
    if item_count <= 0:
        return ""
    verified = int(health.get("verified_body_count", 0) or 0)
    fallback_only = int(health.get("fallback_only_count", 0) or 0)
    status_counts = health.get("fetch_status_counts") or {}
    detail_parts = []
    for key in ("fetched-html", "preserved", "fallback-blocked", "fallback-summary", "preserved-summary", "missing"):
        count = int(status_counts.get(key, 0) or 0)
        if count:
            detail_parts.append("{0} {1}".format(key, count))
    suffix = "（{0}）".format("、".join(detail_parts)) if detail_parts else ""
    return "微信正文抓取：已验证正文 {0}/{1}，仅回退 {2}{3}".format(
        verified, item_count, fallback_only, suffix
    )


def build_success_message(run_date: str, result: Dict[str, Any], summary_url: str) -> str:
    total = int(result.get("total_count", sum((result.get("counts") or {}).values())) or 0)
    lines = [
        "FollowHub 每日汇总已完成（{0}）".format(run_date),
        "共 {0} 条：{1}。".format(total, _count_summary(result)),
    ]
    x_health = _x_health_summary(result)
    if x_health:
        lines.append(x_health + "。")
    wechat_health = _wechat_health_summary(result)
    if wechat_health:
        lines.append(wechat_health + "。")
    lines.append("查看：{0}".format(summary_url))
    return "\n".join(lines)


def build_failure_message(run_date: str, result: Dict[str, Any], summary_url: str) -> str:
    reason = str(result.get("reason") or "未知校验失败").strip()
    lines = [
        "FollowHub 每日汇总未完成（{0}）".format(run_date),
        "截至 23:00 最后一次重试仍未通过：{0}。".format(reason),
    ]
    x_health = _x_health_summary(result)
    if x_health:
        lines.append(x_health + "。")
    wechat_health = _wechat_health_summary(result)
    if wechat_health:
        lines.append(wechat_health + "。")
    lines.append("已发布的部分内容：{0}".format(summary_url))
    lines.append("系统会在次日 07:00 重新开始尝试。")
    return "\n".join(lines)


def build_pending_message(run_date: str, result: Dict[str, Any], summary_url: str) -> str:
    reason = str(result.get("reason") or "未知校验失败").strip()
    lines = [
        "FollowHub 每日汇总仍在重试（{0}）".format(run_date),
        "本轮未完成：{0}。".format(reason),
    ]
    x_health = _x_health_summary(result)
    if x_health:
        lines.append(x_health + "。")
    wechat_health = _wechat_health_summary(result)
    if wechat_health:
        lines.append(wechat_health + "。")
    lines.append("当前页面：{0}".format(summary_url))
    lines.append("系统会在下一次定时触发继续尝试；完成后会再发成功通知。")
    return "\n".join(lines)


def build_notification_idempotency_key(run_date: str, kind: str, message: str) -> str:
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:8]
    return "followhub-{0}-{1}-{2}".format(
        run_date.replace("-", ""),
        str(kind or "note").strip() or "note",
        digest,
    )


def send_lark_message(
    *, lark_cli: str, chat_id: str, message: str, idempotency_key: str
) -> Dict[str, Any]:
    command = [
        lark_cli,
        "im",
        "+messages-send",
        "--chat-id",
        chat_id,
        "--text",
        message,
        "--idempotency-key",
        idempotency_key,
        "--as",
        "bot",
    ]
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "error": (proc.stderr or proc.stdout or "lark-cli failed").strip()[-1000:],
        }
    result: Dict[str, Any] = {"ok": True}
    stdout_text = (proc.stdout or "").strip()
    if stdout_text:
        try:
            parsed = json.loads(stdout_text)
        except ValueError:
            result["output"] = stdout_text[-1000:]
        else:
            result["response"] = parsed
            if isinstance(parsed, dict):
                data = parsed.get("data") or {}
                if isinstance(data, dict):
                    for key in ("message_id", "msg_id", "id"):
                        value = data.get(key)
                        if value:
                            result["message_id"] = str(value)
                            break
    return result


def notify_once(
    *,
    notification_path: Path,
    lark_cli: Optional[str],
    chat_id: Optional[str],
    message: str,
    idempotency_key: str,
) -> bool:
    if notification_path.exists():
        return True
    if not lark_cli or not chat_id:
        return False
    result = send_lark_message(
        lark_cli=lark_cli,
        chat_id=chat_id,
        message=message,
        idempotency_key=idempotency_key,
    )
    if not result.get("ok"):
        print("FollowHub daily notification failed: {0}".format(result.get("error")), file=sys.stderr)
        return False
    write_json_atomic(
        notification_path,
        {
            "sent_at": datetime.now().astimezone().isoformat(),
            "idempotency_key": idempotency_key,
            "message_id": str(result.get("message_id") or ""),
            "response": result.get("response") or {},
        },
    )
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-followhub-scheduled-daily")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config")
    parser.add_argument("--prompt")
    parser.add_argument("--codex-bin")
    parser.add_argument("--state-dir")
    parser.add_argument("--date")
    parser.add_argument("--lark-cli")
    parser.add_argument("--notify-chat-id")
    parser.add_argument("--summary-url", default="https://tenstep.top/follow/")
    parser.add_argument("--final-retry-hour", type=int, default=DEFAULT_FINAL_RETRY_HOUR)
    parser.add_argument("--allow-unavailable-source", action="append", default=[])
    parser.add_argument("--notify-pending-once", action="store_true")
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
    lark_cli = args.lark_cli or shutil.which("lark-cli")
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
    success_notification_path = state_dir / "{0}.success-notified.json".format(run_date)
    pending_notification_path = state_dir / "{0}.pending-notified.json".format(run_date)
    failure_notification_path = state_dir / "{0}.failure-notified.json".format(run_date)
    allow_unavailable_sources = normalize_source_names(args.allow_unavailable_source)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("FollowHub daily is already running for {0}; skipping.".format(run_date))
            return 0

        existing_success = load_json_optional(success_path)
        if existing_success and existing_success.get("schema_version") == SUCCESS_SCHEMA_VERSION:
            current_success = check_daily_success(
                repo,
                run_date,
                config_path,
                allow_unavailable_sources=allow_unavailable_sources,
            )
            if current_success.get("ok"):
                notify_once(
                    notification_path=success_notification_path,
                    lark_cli=lark_cli,
                    chat_id=args.notify_chat_id,
                    message=build_success_message(run_date, existing_success, args.summary_url),
                    idempotency_key=build_notification_idempotency_key(
                        run_date,
                        "success",
                        build_success_message(run_date, existing_success, args.summary_url),
                    ),
                )
                print("FollowHub daily already succeeded for {0}; skipping.".format(run_date))
                return 0
            print(
                "FollowHub daily success marker is stale for {0}: {1}".format(
                    run_date, current_success.get("reason", "unknown verification failure")
                ),
                file=sys.stderr,
            )
            try:
                success_path.unlink()
            except FileNotFoundError:
                pass
            for path in (success_notification_path, failure_notification_path, pending_notification_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

        precheck = check_daily_success(
            repo,
            run_date,
            config_path,
            allow_unavailable_sources=allow_unavailable_sources,
        )
        if precheck.get("ok"):
            precheck["detected_at"] = datetime.now().astimezone().isoformat()
            precheck["source"] = "preflight"
            precheck["schema_version"] = SUCCESS_SCHEMA_VERSION
            precheck["allow_unavailable_sources"] = allow_unavailable_sources
            write_json_atomic(success_path, precheck)
            notify_once(
                notification_path=success_notification_path,
                lark_cli=lark_cli,
                chat_id=args.notify_chat_id,
                message=build_success_message(run_date, precheck, args.summary_url),
                idempotency_key=build_notification_idempotency_key(
                    run_date,
                    "success",
                    build_success_message(run_date, precheck, args.summary_url),
                ),
            )
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
            input=build_prompt(
                prompt_path,
                run_date,
                allow_unavailable_sources=allow_unavailable_sources,
            ),
            text=True,
            cwd=str(repo),
            env=environment,
            check=False,
        )
        postcheck = check_daily_success(
            repo,
            run_date,
            config_path,
            allow_unavailable_sources=allow_unavailable_sources,
        )
        finished_at = datetime.now().astimezone().isoformat()
        finished_hour = datetime.now().astimezone().hour
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
                    "schema_version": SUCCESS_SCHEMA_VERSION,
                    "allow_unavailable_sources": allow_unavailable_sources,
                }
            )
            write_json_atomic(success_path, success)
            notify_once(
                notification_path=success_notification_path,
                lark_cli=lark_cli,
                chat_id=args.notify_chat_id,
                message=build_success_message(run_date, success, args.summary_url),
                idempotency_key=build_notification_idempotency_key(
                    run_date,
                    "success",
                    build_success_message(run_date, success, args.summary_url),
                ),
            )
            print("FollowHub daily succeeded for {0}.".format(run_date))
            return 0

        if finished_hour >= args.final_retry_hour:
            notify_once(
                notification_path=failure_notification_path,
                lark_cli=lark_cli,
                chat_id=args.notify_chat_id,
                message=build_failure_message(run_date, postcheck, args.summary_url),
                idempotency_key=build_notification_idempotency_key(
                    run_date,
                    "failure",
                    build_failure_message(run_date, postcheck, args.summary_url),
                ),
            )
        elif args.notify_pending_once:
            notify_once(
                notification_path=pending_notification_path,
                lark_cli=lark_cli,
                chat_id=args.notify_chat_id,
                message=build_pending_message(run_date, postcheck, args.summary_url),
                idempotency_key=build_notification_idempotency_key(
                    run_date,
                    "pending",
                    build_pending_message(run_date, postcheck, args.summary_url),
                ),
            )

        print(
            "FollowHub daily is still pending for {0}: {1}".format(
                run_date, postcheck.get("reason", "unknown verification failure")
            ),
            file=sys.stderr,
        )
        return proc.returncode if proc.returncode else 1


if __name__ == "__main__":
    raise SystemExit(main())
