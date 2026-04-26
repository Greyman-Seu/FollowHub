#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml


class FollowhubRcloneError(Exception):
    pass


def resolve_config_path(explicit_path: str | None) -> Path:
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    candidates.extend(
        [
            os.environ.get("FOLLOWHUB_CONFIG"),
            os.environ.get("Followhub_Config"),
            "~/.followhub/config.yaml",
        ]
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    searched = [c for c in candidates if c]
    raise FollowhubRcloneError(
        "FollowHub config file not found. Searched: " + ", ".join(str(Path(c).expanduser()) for c in searched)
    )


def load_rclone_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    section = data.get("rclone") or {}
    required = ["account_id", "access_key_id", "secret_access_key", "bucket"]
    missing = [key for key in required if not section.get(key)]
    if missing:
        raise FollowhubRcloneError(
            f"Missing required keys in rclone config: {', '.join(missing)}"
        )
    return section


def ensure_rclone_available() -> None:
    if shutil.which("rclone"):
        return
    raise FollowhubRcloneError(
        "rclone is not installed. Run this script with 'install-help' for installation instructions."
    )


def install_help_text() -> str:
    system = platform.system().lower()
    lines = [
        "rclone install tutorial",
        "",
        "macOS:",
        "  brew install rclone",
        "",
        "Ubuntu/Debian:",
        "  sudo apt-get update",
        "  sudo apt-get install -y rclone",
        "",
        "Universal Linux/macOS:",
        "  sudo -v",
        "  curl https://rclone.org/install.sh | sudo bash",
        "",
        "Windows:",
        "  winget install Rclone.Rclone",
        "",
        "Verify:",
        "  rclone version",
    ]
    if "darwin" in system:
        lines.insert(1, "Detected platform: macOS")
    elif "linux" in system:
        lines.insert(1, "Detected platform: Linux")
    elif "windows" in system:
        lines.insert(1, "Detected platform: Windows")
    else:
        lines.insert(1, f"Detected platform: {platform.system()}")
    return "\n".join(lines)


def normalize_key(key: str) -> str:
    value = key.strip()
    if not value:
        raise FollowhubRcloneError("Remote key/prefix must not be empty.")
    return value.lstrip("/")


def remote_path(config: dict, key: str) -> str:
    return f"followhub-r2:{config['bucket']}/{normalize_key(key)}"


def public_url(config: dict, key: str) -> str:
    clean_key = normalize_key(key)
    base = (config.get("public_base_url") or "").strip().rstrip("/")
    if base:
        return f"{base}/{clean_key}"
    return f"r2://{config['bucket']}/{clean_key}"


@contextmanager
def temp_rclone_config(config: dict):
    fd, path = tempfile.mkstemp(prefix="followhub-rclone-", suffix=".conf")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("[followhub-r2]\n")
            fh.write("type = s3\n")
            fh.write("provider = Cloudflare\n")
            fh.write(f"access_key_id = {config['access_key_id']}\n")
            fh.write(f"secret_access_key = {config['secret_access_key']}\n")
            fh.write(f"endpoint = https://{config['account_id']}.r2.cloudflarestorage.com\n")
            fh.write("acl = private\n")
            fh.write("no_check_bucket = true\n")
        yield path
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def run_rclone(temp_config_path: str, subcommand: str, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["rclone", subcommand, "--config", temp_config_path, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise FollowhubRcloneError("rclone is not installed.") from exc


def fail_from_process(proc: subprocess.CompletedProcess, subcommand: str, target: str) -> None:
    reason = (proc.stderr or proc.stdout or "").strip()
    if not reason:
        reason = f"rclone exited with code {proc.returncode}"
    raise FollowhubRcloneError(f"{subcommand} failed for {target}: {reason}")


def output(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1

    message = payload.get("message")
    if message:
        print(message)
        return 0 if payload.get("ok", True) else 1

    if "items" in payload:
        print(json.dumps(payload["items"], ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 1


def command_check(as_json: bool) -> int:
    path = shutil.which("rclone")
    if not path:
        return output(
            {
                "ok": False,
                "message": "rclone is not installed. Run 'install-help' for instructions.",
            },
            as_json,
        )

    proc = subprocess.run(["rclone", "version"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return output(
            {
                "ok": False,
                "message": "rclone is installed but 'rclone version' failed.",
                "stderr": (proc.stderr or "").strip(),
            },
            as_json,
        )

    first_line = (proc.stdout or "").splitlines()[0] if proc.stdout else "rclone installed"
    return output(
        {
            "ok": True,
            "path": path,
            "version": first_line,
            "message": f"{first_line} ({path})",
        },
        as_json,
    )


def command_install_help(as_json: bool) -> int:
    text = install_help_text()
    return output({"ok": True, "message": text}, as_json)


def command_copyto(args: argparse.Namespace, config: dict, as_json: bool) -> int:
    target = remote_path(config, args.key)
    with temp_rclone_config(config) as temp_config_path:
        proc = run_rclone(temp_config_path, "copyto", [args.src, target])
    if proc.returncode != 0:
        fail_from_process(proc, "copyto", target)
    url = public_url(config, args.key)
    return output(
        {
            "ok": True,
            "command": "copyto",
            "src": args.src,
            "key": normalize_key(args.key),
            "remote": target,
            "url": url,
            "message": f"Uploaded to {url}",
        },
        as_json,
    )


def command_copy_or_sync(args: argparse.Namespace, config: dict, as_json: bool, subcommand: str) -> int:
    target = remote_path(config, args.prefix)
    with temp_rclone_config(config) as temp_config_path:
        proc = run_rclone(temp_config_path, subcommand, [args.src, target])
    if proc.returncode != 0:
        fail_from_process(proc, subcommand, target)
    url = public_url(config, args.prefix)
    verb = "Copied" if subcommand == "copy" else "Synced"
    return output(
        {
            "ok": True,
            "command": subcommand,
            "src": args.src,
            "prefix": normalize_key(args.prefix),
            "remote": target,
            "url": url,
            "message": f"{verb} to {url}",
        },
        as_json,
    )


def command_lsjson(args: argparse.Namespace, config: dict, as_json: bool) -> int:
    target = remote_path(config, args.prefix)
    with temp_rclone_config(config) as temp_config_path:
        proc = run_rclone(temp_config_path, "lsjson", [target])
    if proc.returncode != 0:
        fail_from_process(proc, "lsjson", target)
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise FollowhubRcloneError(f"lsjson returned invalid JSON for {target}") from exc
    return output(
        {
            "ok": True,
            "command": "lsjson",
            "prefix": normalize_key(args.prefix),
            "remote": target,
            "items": items,
            "message": f"Listed {len(items)} objects under {config['bucket']}/{normalize_key(args.prefix)}",
        },
        as_json,
    )


def command_deletefile(args: argparse.Namespace, config: dict, as_json: bool) -> int:
    target = remote_path(config, args.key)
    with temp_rclone_config(config) as temp_config_path:
        proc = run_rclone(temp_config_path, "deletefile", [target])
    if proc.returncode != 0:
        fail_from_process(proc, "deletefile", target)
    key = normalize_key(args.key)
    return output(
        {
            "ok": True,
            "command": "deletefile",
            "key": key,
            "remote": target,
            "message": f"Deleted {config['bucket']}/{key}",
        },
        as_json,
    )


def command_delete(args: argparse.Namespace, config: dict, as_json: bool, subcommand: str) -> int:
    target = remote_path(config, args.prefix)
    if subcommand == "purge" and not args.force:
        raise FollowhubRcloneError("purge requires --force because it is destructive.")
    with temp_rclone_config(config) as temp_config_path:
        proc = run_rclone(temp_config_path, subcommand, [target])
    if proc.returncode != 0:
        fail_from_process(proc, subcommand, target)
    prefix = normalize_key(args.prefix)
    verb = "Deleted" if subcommand == "delete" else "Purged"
    return output(
        {
            "ok": True,
            "command": subcommand,
            "prefix": prefix,
            "remote": target,
            "message": f"{verb} {config['bucket']}/{prefix}",
        },
        as_json,
    )


def command_url(args: argparse.Namespace, config: dict, as_json: bool) -> int:
    key = normalize_key(args.key)
    url = public_url(config, key)
    return output(
        {
            "ok": True,
            "command": "url",
            "key": key,
            "url": url,
            "message": url,
        },
        as_json,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FollowHub rclone wrapper for Cloudflare R2.")
    parser.add_argument("--config-file", help="Override FollowHub config YAML path.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Check whether rclone is installed.")
    subparsers.add_parser("install-help", help="Print rclone installation instructions.")

    parser_copyto = subparsers.add_parser("copyto", help="Upload one file to an exact object key.")
    parser_copyto.add_argument("src", help="Local file path.")
    parser_copyto.add_argument("key", help="Remote object key inside the configured bucket.")

    parser_copy = subparsers.add_parser("copy", help="Upload a directory without deleting remote extras.")
    parser_copy.add_argument("src", help="Local directory or file path.")
    parser_copy.add_argument("prefix", help="Remote prefix inside the configured bucket.")

    parser_sync = subparsers.add_parser("sync", help="Mirror a local path to a remote prefix.")
    parser_sync.add_argument("src", help="Local directory path.")
    parser_sync.add_argument("prefix", help="Remote prefix inside the configured bucket.")

    parser_ls = subparsers.add_parser("lsjson", help="List objects under a remote prefix.")
    parser_ls.add_argument("prefix", help="Remote prefix inside the configured bucket.")

    parser_deletefile = subparsers.add_parser("deletefile", help="Delete one remote object.")
    parser_deletefile.add_argument("key", help="Remote object key inside the configured bucket.")

    parser_delete = subparsers.add_parser("delete", help="Delete objects under a remote prefix.")
    parser_delete.add_argument("prefix", help="Remote prefix inside the configured bucket.")

    parser_purge = subparsers.add_parser("purge", help="Purge a remote prefix completely.")
    parser_purge.add_argument("prefix", help="Remote prefix inside the configured bucket.")
    parser_purge.add_argument("--force", action="store_true", help="Acknowledge this destructive operation.")

    parser_url = subparsers.add_parser("url", help="Resolve a remote key to the public URL.")
    parser_url.add_argument("key", help="Remote object key inside the configured bucket.")
    return parser


def normalize_global_args(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    deferred: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--json":
            deferred.append(token)
            i += 1
            continue
        if token == "--config-file":
            deferred.append(token)
            if i + 1 >= len(argv):
                raise FollowhubRcloneError("--config-file requires a path.")
            deferred.append(argv[i + 1])
            i += 2
            continue
        normalized.append(token)
        i += 1
    return deferred + normalized


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(normalize_global_args(sys.argv[1:]))
        as_json = args.json

        if args.command == "check":
            return command_check(as_json)
        if args.command == "install-help":
            return command_install_help(as_json)

        if args.command == "url":
            config_path = resolve_config_path(args.config_file)
            config = load_rclone_config(config_path)
            return command_url(args, config, as_json)

        ensure_rclone_available()
        config_path = resolve_config_path(args.config_file)
        config = load_rclone_config(config_path)

        if args.command == "copyto":
            return command_copyto(args, config, as_json)
        if args.command == "copy":
            return command_copy_or_sync(args, config, as_json, "copy")
        if args.command == "sync":
            return command_copy_or_sync(args, config, as_json, "sync")
        if args.command == "lsjson":
            return command_lsjson(args, config, as_json)
        if args.command == "deletefile":
            return command_deletefile(args, config, as_json)
        if args.command == "delete":
            return command_delete(args, config, as_json, "delete")
        if args.command == "purge":
            return command_delete(args, config, as_json, "purge")
        raise FollowhubRcloneError(f"Unsupported command: {args.command}")
    except FollowhubRcloneError as exc:
        return output({"ok": False, "message": str(exc)}, as_json)


if __name__ == "__main__":
    sys.exit(main())
