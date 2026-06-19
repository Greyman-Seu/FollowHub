#!/usr/bin/env python3
"""Artifact-driven orchestrator for the RSS daily skill."""

from __future__ import annotations

import argparse
import json
import os
import html
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional
import re

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "rss-daily-output"
DEFAULT_COLLECT_OUTPUT_ROOT = REPO_ROOT / "rss-collect-output"


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def stage_log(stage: str, message: str, **details: object) -> None:
    payload = {"stage": stage, "message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def today_string() -> str:
    return date.today().isoformat()


def parse_date(value: str) -> date:
    return date.fromisoformat(str(value).strip())


def load_yaml(path: Path) -> Dict[str, object]:
    if yaml is None:
        fail("PyYAML is required to load rss-daily config files.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        fail(f"Config file must contain a top-level mapping: {path}")
    return data


def resolve_config_path(explicit: Optional[str]) -> Path:
    candidates = [
        explicit,
        os.environ.get("FOLLOWHUB_CONFIG"),
        str(REPO_ROOT / "followhub.yaml"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    fail("Could not resolve FollowHub config. Pass --config or set FOLLOWHUB_CONFIG.")


def run_command(args: List[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        fail(f"Command failed: {' '.join(args)}\n{detail}")
    return proc


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def previous_date_string(run_date: str) -> str:
    return (parse_date(run_date) - timedelta(days=1)).isoformat()


@dataclass
class DailyPaths:
    run_root: Path
    state_root: Path
    raw_json: Path
    normalized_json: Path
    fetched_json: Path
    deduped_json: Path
    clustered_json: Path
    story_history_json: Path
    story_ledger_json: Path
    prefilter_input: Path
    prefilter_results: Path
    filter_input: Path
    filter_results: Path
    enrich_results: Path
    digest_json: Path
    publish_dir: Path
    verify_json: Path


def build_paths(run_root: Path, output_root: Path, run_date: str) -> DailyPaths:
    state_root = output_root / "_state"
    return DailyPaths(
        run_root=run_root,
        state_root=state_root,
        raw_json=DEFAULT_COLLECT_OUTPUT_ROOT / f"{run_date}-raw.json",
        normalized_json=run_root / "normalize" / "normalized_items.json",
        fetched_json=run_root / "fetch" / "fetched_items.json",
        deduped_json=run_root / "dedupe" / "deduped_items.json",
        clustered_json=run_root / "cluster" / "clustered_items.json",
        story_history_json=run_root / "story-history.json",
        story_ledger_json=state_root / "story-ledger.json",
        prefilter_input=run_root / "prefilter_input.json",
        prefilter_results=run_root / "prefilter_results.json",
        filter_input=run_root / "filter_input.json",
        filter_results=run_root / "filter_results.json",
        enrich_results=run_root / "enrich_results.json",
        digest_json=run_root / "daily-digest.json",
        publish_dir=run_root / "publish-out",
        verify_json=run_root / "verify.json",
    )


def rss_focus(config: Dict[str, Any]) -> Dict[str, Any]:
    rss = config.get("rss") or {}
    if not isinstance(rss, dict):
        return {"keywords": [], "exclude_keywords": [], "topic_context": ""}
    return {
        "keywords": list(rss.get("keywords") or []),
        "exclude_keywords": list(rss.get("exclude_keywords") or []),
        "topic_context": str(rss.get("topic_context") or ""),
        "strict_date_only": bool(rss.get("strict_date_only", False)),
    }


def rss_collect_runtime(config: Dict[str, Any]) -> Dict[str, int]:
    rss = config.get("rss") or {}
    collect = rss.get("collect") if isinstance(rss, dict) else {}
    if not isinstance(collect, dict):
        collect = {}
    max_workers = int(collect.get("max_workers") or 8)
    request_timeout_seconds = int(collect.get("request_timeout_seconds") or 30)
    return {
        "max_workers": max(1, max_workers),
        "request_timeout_seconds": max(1, request_timeout_seconds),
    }


AD_HINTS = {
    "广告",
    "赞助",
    "推广",
    "软文",
    "课程",
    "训练营",
    "招生",
    "报名",
    "社群",
    "优惠",
    "限时",
    "付费",
    "招聘",
    "内推",
    "sponsor",
    "sponsored",
    "promo",
    "promotion",
    "discount",
    "course",
    "bootcamp",
    "hiring",
    "job",
}

DOMAIN_HINTS = {
    "physical-embodied-intelligence": {
        "robot",
        "robotics",
        "embodied",
        "manipulation",
        "vla",
        "grasp",
        "navigation",
        "humanoid",
        "机器人",
        "具身",
        "机械臂",
    },
    "aigc": {
        "image generation",
        "video generation",
        "diffusion",
        "text-to-image",
        "text-to-video",
        "image",
        "video",
        "图像生成",
        "视频生成",
        "扩散",
    },
    "llm-vlm": {
        "llm",
        "vlm",
        "multimodal",
        "reasoning",
        "agentic",
        "foundation model",
        "大模型",
        "多模态",
        "推理模型",
    },
    "agent": {
        "agent",
        "workflow",
        "tool use",
        "tool-use",
        "planning",
        "智能体",
        "工具调用",
        "工作流",
    },
}

TECH_SIGNAL_HINTS = {
    "paper",
    "arxiv",
    "dataset",
    "benchmark",
    "model",
    "weights",
    "release",
    "launch",
    "open source",
    "open-source",
    "github",
    "policy",
    "robot",
    "robotics",
    "vla",
    "world model",
    "diffusion",
    "multimodal",
    "vlm",
    "llm",
    "reasoning",
    "tool calling",
    "agent",
    "mocap",
    "vision",
    "video generation",
    "image generation",
    "evaluation",
    "training",
    "inference",
    "openai",
    "claude",
    "gemini",
    "deepmind",
    "anthropic",
    "transformer",
    "post-training",
    "post training",
    "rl",
    "reinforcement learning",
    "gpu",
    "token",
    "compute",
    "code agent",
    "vision-language-action",
    "机器人",
    "具身",
    "多模态",
    "大模型",
    "推理",
    "开源",
    "算力",
    "强化学习",
    "后训练",
    "世界模型",
    "视频生成",
    "图像生成",
    "模型",
    "论文",
    "顶会",
    "顶刊",
    "思维链",
    "奖励",
    "ai工厂",
}

X_PROMO_HINTS = {
    "amzn.to",
    "what you will learn",
    "academy.",
    "sign up",
    "register",
    "prelaunch",
    "buy now",
    "available now",
    "order now",
    "course",
    "bootcamp",
    "sponsor",
    "sponsored",
    "promotion",
    "英雄帖",
    "报名",
    "招聘",
    "训练营",
    "课程",
    "活动",
    "闭门交流",
}

FOLLOWUP_HINTS = {
    "recap",
    "update",
    "followup",
    "follow-up",
    "details",
    "breakdown",
    "analysis",
    "deep dive",
    "new paper",
    "new model",
    "发布",
    "更新",
    "进展",
    "复盘",
    "解读",
    "详解",
    "新作",
    "新模型",
}

SUMMARY_HTML_TAG_PAT = re.compile(r"<[^>]+>")
RT_PREFIX_PAT = re.compile(r"^RT by @[^:]+:\\s*", re.IGNORECASE)
URL_INLINE_PAT = re.compile(r"https?://\\S+", re.IGNORECASE)


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def strip_summary_markup(value: str) -> str:
    text = SUMMARY_HTML_TAG_PAT.sub(" ", str(value or ""))
    text = html.unescape(text)
    text = URL_INLINE_PAT.sub("", text)
    return " ".join(text.split()).strip()


def truncate_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def contains_cjk(value: str) -> bool:
    text = str(value or "")
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def count_cjk_chars(value: str) -> int:
    return sum(1 for char in str(value or "") if "\u4e00" <= char <= "\u9fff")


def strip_auto_cn_prefix(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^X\s*动态[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^原文摘要[:：]\s*", "", text)
    return text.strip()


def first_sentence(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[。！？!?])\s+", text, maxsplit=1)
    return parts[0].strip() if parts else text


def split_title_parts(title: str) -> tuple[str, str]:
    text = " ".join(str(title or "").split()).strip().strip("。")
    if not text:
        return "", ""
    for sep in ("｜", "|", "：", ":"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(" “ ” \" "), right.strip(" “ ” \" ")
    if "？" in text:
        left, right = text.split("？", 1)
        return left.strip(" “ ” \" "), right.strip(" “ ” \" ")
    if "?" in text:
        left, right = text.split("?", 1)
        return left.strip(" “ ” \" "), right.strip(" “ ” \" ")
    return text, ""


def needs_x_auto_refresh(value: str, *, one_liner: bool) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    payload = strip_auto_cn_prefix(text)
    if not payload:
        return True
    if count_cjk_chars(payload) >= (6 if one_liner else 10):
        return False
    if one_liner and re.match(r"^X\s*动态[:：]", text, flags=re.IGNORECASE):
        return True
    if not one_liner and text.startswith("原文摘要："):
        return True
    return False


def needs_wechat_auto_refresh_one_liner(existing: str, title: str) -> bool:
    text = str(existing or "").strip()
    if not text:
        return True
    if text == str(title or "").strip():
        return True
    if "给出的回答是" in text and "？" in text:
        return True
    return count_cjk_chars(text) < 12


def needs_wechat_auto_refresh_summary(existing: str, title: str) -> bool:
    text = str(existing or "").strip()
    if not text:
        return True
    if text == str(title or "").strip():
        return True
    if "给出的答案是" in text and "？" in text:
        return True
    return count_cjk_chars(text) < 24


def infer_x_one_liner_zh(entry: Dict[str, Any]) -> str:
    title = strip_summary_markup(str(entry.get("title") or ""))
    summary = strip_summary_markup(str(entry.get("summary") or ""))
    content = strip_summary_markup(str(entry.get("content_text") or ""))
    title = RT_PREFIX_PAT.sub("", title)
    combined = " ".join(part for part in (title, summary, content) if part)
    lowered = normalize_text(combined)
    is_retweet = bool(re.match(r"^rt\b", normalize_text(str(entry.get("title") or ""))))

    if contains_cjk(title):
        return truncate_text(first_sentence(title), 42)
    if contains_cjk(summary):
        return truncate_text(first_sentence(summary), 50)
    if "persuasion" in lowered or "persuade" in lowered:
        return "讨论了 AI 说服能力及其潜在社会影响。"
    if any(token in lowered for token in ("spend control", "credit usage", "admin console", "enterprise")):
        return "发布了企业额度分析与管理员支出控制相关更新。"
    if any(token in lowered for token in ("jailbreak", "security", "safety", "blocked request")):
        return "讨论了模型越狱与安全限制相关动态。"
    if any(token in lowered for token in ("open weights", "open source", "open model", "open models")):
        return "讨论了开源模型与开放生态的最新进展。"
    if any(token in lowered for token in ("benchmark", "evaluation", "leaderboard", "eval")):
        return "分享了一个评测结果或 benchmark 观察。"
    if any(token in lowered for token in ("robot", "robotics", "vla", "manipulation", "embodied")):
        return "分享了机器人或具身智能相关进展。"
    if any(token in lowered for token in ("video", "demo", "scanner", "visualizer", "livestream")):
        return "分享了一段演示或产品展示。"
    if any(token in lowered for token in ("launch", "launched", "release", "released", "rolling out", "available", "update", "updated")):
        return "发布了一项新功能或产品更新。"
    if any(token in lowered for token in ("paper", "research", "study", "arxiv")):
        return "分享了一项研究进展。"
    if any(token in lowered for token in ("model", "llm", "ai", "agent", "workflow")):
        return "分享了一条 AI 相关动态。"
    if is_retweet:
        return "转发并评论了一条值得关注的动态。"
    return "分享了一条值得查看的动态。"


def infer_wechat_one_liner_zh(entry: Dict[str, Any]) -> str:
    title = strip_summary_markup(str(entry.get("title") or ""))
    summary = strip_summary_markup(str(entry.get("summary") or ""))
    left, right = split_title_parts(title)
    right_clean = right.rstrip("？?。")
    right_is_question = ("？" in right) or ("?" in right)
    if "？" in title and right:
        if right_is_question and summary:
            return truncate_text(f"文章讨论{left}，对“{right_clean}”的判断是{summary}。", 72)
        if summary and summary not in right:
            return truncate_text(f"文章围绕“{left}”展开，给出的回答是{right}，并强调{summary}。", 72)
        return truncate_text(f"文章围绕“{left}”展开，给出的回答是{right}。", 66)
    if right and summary:
        if summary in right or right in summary:
            return truncate_text(f"文章介绍{right}。", 64)
        return truncate_text(f"文章介绍{right}，重点是{summary}。", 72)
    if summary and summary != title:
        topic = left or title
        return truncate_text(f"文章围绕{topic}展开，重点是{summary}。", 72)
    return truncate_text(title, 60)


def infer_wechat_summary_cn(entry: Dict[str, Any]) -> str:
    title = strip_summary_markup(str(entry.get("title") or ""))
    summary = strip_summary_markup(str(entry.get("summary") or ""))
    left, right = split_title_parts(title)
    right_clean = right.rstrip("？?。")
    right_is_question = ("？" in right) or ("?" in right)
    if "？" in title and right:
        if right_is_question and summary:
            return truncate_text(f"本文讨论{left}，围绕“{right_clean}”这个问题给出的结论是{summary}。", 140)
        if summary and summary not in right:
            return truncate_text(f"本文从“{left}”这个问题切入，给出的答案是{right}，并进一步指出{summary}。", 140)
        return truncate_text(f"本文从“{left}”这个问题切入，给出的答案是{right}。", 120)
    if right and summary:
        if summary in right or right in summary:
            return truncate_text(f"本文介绍{left or title}，核心内容是{right}。", 130)
        return truncate_text(f"本文介绍{left or title}，核心内容是{right}，并强调{summary}。", 140)
    if summary and summary != title:
        return truncate_text(f"本文围绕{title}展开，重点信息是{summary}。", 130)
    return truncate_text(title, 100)


def combined_entry_text(entry: Dict[str, Any]) -> str:
    return normalize_text(
        " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("summary") or ""),
                str(entry.get("content_text") or ""),
                " ".join(str(tag) for tag in (entry.get("tags") or [])),
            ]
        )
    )


def cleaned_entry_body(entry: Dict[str, Any]) -> str:
    parts = [
        strip_summary_markup(str(entry.get("title") or "")),
        strip_summary_markup(str(entry.get("summary") or "")),
        strip_summary_markup(str(entry.get("content_text") or "")),
        " ".join(str(tag) for tag in (entry.get("tags") or [])),
    ]
    return " ".join(part for part in parts if part).strip()


def token_match_count(text: str, tokens: List[str]) -> int:
    count = 0
    for token in tokens:
        value = normalize_text(token)
        if value and value in text:
            count += 1
    return count


def looks_like_ad(text: str, exclude_keywords: List[str]) -> bool:
    if token_match_count(text, exclude_keywords) > 0:
        return True
    return any(hint in text for hint in AD_HINTS)


def has_technical_signal(text: str) -> bool:
    lowered = normalize_text(text)
    return any(hint in lowered for hint in TECH_SIGNAL_HINTS)


def looks_like_x_promo_or_noise(entry: Dict[str, Any], text: str) -> bool:
    if str(entry.get("source_type") or "").strip().lower() != "x":
        return False
    lowered = normalize_text(text)
    title = strip_summary_markup(str(entry.get("title") or ""))
    title_lower = title.lower()
    if any(hint in lowered for hint in X_PROMO_HINTS):
        return True
    if title_lower in {"image", "video"}:
        return True
    if title_lower.startswith("rt by @") and not has_technical_signal(text):
        return True
    if len(title.split()) <= 4 and not has_technical_signal(text):
        return True
    return False


def should_keep_recent_repeat(entry: Dict[str, Any], text: str) -> bool:
    story_status = str(entry.get("story_status") or "").strip().lower()
    history_hint = entry.get("history_hint") or {}
    history_source_overlap = bool(history_hint.get("history_source_overlap")) if isinstance(history_hint, dict) else False
    lowered = normalize_text(text)
    if story_status == "followup" and not history_source_overlap and any(hint in lowered for hint in FOLLOWUP_HINTS):
        return True
    return False


def collect_daily(config_path: Path, raw_json_path: Path) -> Dict[str, Any]:
    stage_log("collect", "start", config=str(config_path), output=str(raw_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-collect" / "rss_collect.py"),
            "collect",
            "--config",
            str(config_path),
            "--output",
            str(raw_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(raw_json_path)
    stage_log("collect", "done", item_count=int(payload.get("item_count", 0) or 0), raw_json=str(raw_json_path))
    return payload


def filter_items_to_run_date(payload: Dict[str, Any], run_date: str, output_path: Path) -> Dict[str, Any]:
    items = []
    for item in list(payload.get("items") or []):
        published_at = str(item.get("published_at") or "")
        if published_at[:10] == run_date:
            items.append(item)
    filtered = dict(payload)
    filtered["items"] = items
    filtered["item_count"] = len(items)
    write_json(output_path, filtered)
    stage_log("collect", "date-filtered", run_date=run_date, item_count=len(items), raw_json=str(output_path))
    return filtered


def normalize_daily(raw_json_path: Path, normalized_json_path: Path) -> Dict[str, Any]:
    stage_log("normalize", "start", input=str(raw_json_path), output=str(normalized_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-normalize" / "rss_normalize.py"),
            "normalize",
            "--input",
            str(raw_json_path),
            "--output",
            str(normalized_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(normalized_json_path)
    stage_log("normalize", "done", item_count=int(payload.get("item_count", 0) or 0), normalized_json=str(normalized_json_path))
    return payload


def fetch_daily(
    normalized_json_path: Path,
    fetched_json_path: Path,
    *,
    max_workers: int,
    request_timeout_seconds: int,
) -> Dict[str, Any]:
    stage_log(
        "fetch",
        "start",
        input=str(normalized_json_path),
        output=str(fetched_json_path),
        max_workers=max_workers,
        request_timeout_seconds=request_timeout_seconds,
    )
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-fetch" / "rss_fetch.py"),
            "fetch",
            "--input",
            str(normalized_json_path),
            "--output",
            str(fetched_json_path),
            "--max-workers",
            str(max_workers),
            "--request-timeout-seconds",
            str(request_timeout_seconds),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(fetched_json_path)
    stage_log(
        "fetch",
        "done",
        item_count=int(payload.get("item_count", 0) or 0),
        fetched_json=str(fetched_json_path),
        max_workers=int(payload.get("max_workers", max_workers) or max_workers),
    )
    return payload


def dedupe_daily(fetched_json_path: Path, deduped_json_path: Path) -> Dict[str, Any]:
    stage_log("dedupe", "start", input=str(fetched_json_path), output=str(deduped_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-dedupe" / "rss_dedupe.py"),
            "dedupe",
            "--input",
            str(fetched_json_path),
            "--output",
            str(deduped_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(deduped_json_path)
    stage_log("dedupe", "done", item_count=int(payload.get("item_count", 0) or 0), deduped_json=str(deduped_json_path))
    return payload


def cluster_daily(deduped_json_path: Path, clustered_json_path: Path) -> Dict[str, Any]:
    stage_log("cluster", "start", input=str(deduped_json_path), output=str(clustered_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-cluster" / "rss_cluster.py"),
            "cluster",
            "--input",
            str(deduped_json_path),
            "--output",
            str(clustered_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(clustered_json_path)
    agent_handoff = payload.get("agent_handoff") or {}
    stage_log(
        "cluster",
        "done",
        item_count=int(payload.get("item_count", 0) or 0),
        story_count=int(payload.get("story_count", 0) or 0),
        agent_handoff_required=bool(agent_handoff.get("required", False)),
        clustered_json=str(clustered_json_path),
    )
    return payload


def iter_digest_story_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    stories = payload.get("stories")
    if isinstance(stories, list) and stories:
        return [item for item in stories if isinstance(item, dict)]

    items: List[Dict[str, Any]] = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def build_story_history(publish_root: Path, run_date: str, lookback_days: int, output_path: Path) -> Dict[str, Any]:
    history: Dict[str, Dict[str, Any]] = {}
    current_day = parse_date(run_date)
    for offset in range(1, max(0, lookback_days) + 1):
        day = (current_day - timedelta(days=offset)).isoformat()
        digest_path = publish_root / day / "daily-digest.json"
        if not digest_path.exists():
            continue
        try:
            payload = load_json(digest_path)
        except Exception:
            continue
        for item in iter_digest_story_items(payload):
            story_id = str(item.get("story_id") or "").strip()
            if not story_id:
                continue
            row = history.setdefault(
                story_id,
                {
                    "story_id": story_id,
                    "seen_dates": [],
                    "last_seen_date": "",
                    "latest_story_status": "",
                    "latest_title": "",
                    "source_types": [],
                    "source_names": [],
                    "max_mention_count": 0,
                },
            )
            if day not in row["seen_dates"]:
                row["seen_dates"].append(day)
                row["seen_dates"].sort()
            for source_type in item.get("source_types") or ([] if not item.get("source_type") else [item.get("source_type")]):
                source_type_value = str(source_type or "").strip()
                if source_type_value and source_type_value not in row["source_types"]:
                    row["source_types"].append(source_type_value)
            for source_name in item.get("source_names") or ([] if not item.get("source_name") else [item.get("source_name")]):
                source_name_value = str(source_name or "").strip()
                if source_name_value and source_name_value not in row["source_names"]:
                    row["source_names"].append(source_name_value)
            row["max_mention_count"] = max(int(row.get("max_mention_count") or 0), int(item.get("mention_count") or 0))
            if day >= str(row.get("last_seen_date") or ""):
                row["last_seen_date"] = day
                row["latest_story_status"] = str(item.get("story_status") or "")
                row["latest_title"] = str(item.get("title") or "")

    payload = {
        "mode": "rss-story-history",
        "run_date": run_date,
        "lookback_days": lookback_days,
        "story_count": len(history),
        "stories": sorted(history.values(), key=lambda item: str(item.get("last_seen_date") or ""), reverse=True),
    }
    write_json(output_path, payload)
    return payload


def load_story_ledger(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"mode": "rss-story-ledger", "story_count": 0, "stories": []}
    try:
        payload = load_json(path)
    except Exception:
        return {"mode": "rss-story-ledger", "story_count": 0, "stories": []}
    if not isinstance(payload.get("stories"), list):
        return {"mode": "rss-story-ledger", "story_count": 0, "stories": []}
    return payload


def build_combined_story_history(recent_history: Dict[str, Any], ledger_payload: Dict[str, Any], output_path: Path) -> Dict[str, Any]:
    combined: Dict[str, Dict[str, Any]] = {}
    for source_payload, source_name in ((ledger_payload, "ledger"), (recent_history, "recent")):
        for item in source_payload.get("stories") or []:
            if not isinstance(item, dict):
                continue
            story_id = str(item.get("story_id") or "").strip()
            if not story_id:
                continue
            row = combined.setdefault(
                story_id,
                {
                    "story_id": story_id,
                    "seen_dates": [],
                    "last_seen_date": "",
                    "latest_story_status": "",
                    "latest_title": "",
                    "source_types": [],
                    "source_names": [],
                    "max_mention_count": 0,
                    "history_sources": [],
                },
            )
            for seen_date in item.get("seen_dates") or ([] if not item.get("last_seen_date") else [item.get("last_seen_date")]):
                seen_date_value = str(seen_date or "").strip()
                if seen_date_value and seen_date_value not in row["seen_dates"]:
                    row["seen_dates"].append(seen_date_value)
            row["seen_dates"].sort()
            for source_type in item.get("source_types") or []:
                source_type_value = str(source_type or "").strip()
                if source_type_value and source_type_value not in row["source_types"]:
                    row["source_types"].append(source_type_value)
            for source_name_value in item.get("source_names") or []:
                normalized_name = str(source_name_value or "").strip()
                if normalized_name and normalized_name not in row["source_names"]:
                    row["source_names"].append(normalized_name)
            row["max_mention_count"] = max(int(row.get("max_mention_count") or 0), int(item.get("max_mention_count") or item.get("mention_count") or 0))
            candidate_last_seen = str(item.get("last_seen_date") or "").strip()
            if candidate_last_seen >= str(row.get("last_seen_date") or ""):
                row["last_seen_date"] = candidate_last_seen
                row["latest_story_status"] = str(item.get("latest_story_status") or item.get("story_status") or "")
                row["latest_title"] = str(item.get("latest_title") or item.get("title") or "")
            if source_name not in row["history_sources"]:
                row["history_sources"].append(source_name)

    payload = {
        "mode": "rss-story-history",
        "run_date": str(recent_history.get("run_date") or ""),
        "lookback_days": int(recent_history.get("lookback_days") or 0),
        "story_count": len(combined),
        "stories": sorted(combined.values(), key=lambda item: str(item.get("last_seen_date") or ""), reverse=True),
    }
    write_json(output_path, payload)
    return payload


def build_history_hint(entry: Dict[str, Any], history_by_story_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    story_id = str(entry.get("story_id") or "").strip()
    source_name = str(entry.get("source_name") or "").strip()
    story_status = str(entry.get("story_status") or "").strip()
    history = history_by_story_id.get(story_id) if story_id else None
    seen_recently = history is not None
    history_source_names = list(history.get("source_names") or []) if history else []
    source_overlap = source_name in history_source_names if source_name else False
    return {
        "seen_recently": seen_recently,
        "current_story_status": story_status,
        "last_seen_date": str(history.get("last_seen_date") or "") if history else "",
        "latest_story_status": str(history.get("latest_story_status") or "") if history else "",
        "history_source_overlap": source_overlap,
        "history_source_count": len(history_source_names),
        "history_publish_count": int(history.get("publish_count") or 0) if history else 0,
        "history_max_mention_count": int(history.get("max_mention_count") or 0) if history else 0,
        "history_latest_title": str(history.get("latest_title") or "") if history else "",
    }


def build_prefilter_reviewer_prompt() -> str:
    return (
        "Review this RSS item using title/source-level signals first. "
        "Use recent story history to decide whether it looks like a new story, a repeat, or a meaningful followup. "
        "Prefer drop for obvious repeat coverage, keep for clear in-scope new items, and uncertain for borderline followups."
    )


def build_filter_reviewer_prompt() -> str:
    return (
        "Review this RSS item for final daily digest inclusion. "
        "Use content, recent story history, and history_hint together. "
        "Exclude obvious repeats, include strong in-scope new items, and include followups only when they add signal beyond prior coverage."
    )


def build_prefilter_reviewer_checklist() -> List[str]:
    return [
        "Does the title/source clearly match the configured interest scope?",
        "Does recent history suggest this is just a repeat of a recently pushed story?",
        "If it is a followup, is there enough signal to keep it for deeper review?",
        "Is the item likely ad-like, promotional, or otherwise low-signal?",
    ]


def build_filter_reviewer_checklist() -> List[str]:
    return [
        "Does the item add meaningful signal for today's digest?",
        "Is it a repeat of a recently pushed story without new substance?",
        "If marked followup, does it materially advance the prior story?",
        "Do source overlap, publish count, or prior mention count raise the inclusion bar?",
        "Should the item be excluded even if it matches scope because it is low-signal or repetitive?",
    ]


def build_prefilter_decision_criteria() -> Dict[str, str]:
    return {
        "keep": "Clear in-scope new item or strong followup worth deeper review.",
        "drop": "Off-topic, ad-like, obvious repeat, or too low-signal to keep reviewing.",
        "uncertain": "Borderline followup or weak title/source match that needs full content review.",
    }


def build_filter_decision_criteria() -> Dict[str, str]:
    return {
        "include": "Strong new item or meaningful followup that improves today's digest.",
        "exclude": "Repeat, low-signal recap, ad-like item, or in-scope but not worth today's attention.",
    }


def build_prefilter_output_schema() -> Dict[str, Any]:
    return {
        "items": [
            {
                "id": "string",
                "decision": "keep|drop|uncertain",
                "reason": "short string",
            }
        ]
    }


def build_filter_output_schema() -> Dict[str, Any]:
    return {
        "items": [
            {
                "id": "string",
                "include_in_digest": "boolean",
                "domains": [{"slug": "string", "name": "string"}],
                "one_liner_zh": "string",
                "summary_cn": "string",
                "reason": "short string",
            }
        ]
    }


def update_story_ledger(ledger_path: Path, digest_payload: Dict[str, Any], run_date: str) -> Dict[str, Any]:
    existing = load_story_ledger(ledger_path)
    stories_by_id: Dict[str, Dict[str, Any]] = {}
    for item in existing.get("stories") or []:
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("story_id") or "").strip()
        if story_id:
            stories_by_id[story_id] = dict(item)

    for item in iter_digest_story_items(digest_payload):
        story_id = str(item.get("story_id") or "").strip()
        if not story_id:
            continue
        row = stories_by_id.setdefault(
            story_id,
            {
                "story_id": story_id,
                "first_seen_date": run_date,
                "seen_dates": [],
                "last_seen_date": "",
                "latest_story_status": "",
                "latest_title": "",
                "source_types": [],
                "source_names": [],
                "max_mention_count": 0,
                "publish_count": 0,
            },
        )
        if not row.get("first_seen_date"):
            row["first_seen_date"] = run_date
        if run_date not in row["seen_dates"]:
            row["seen_dates"].append(run_date)
            row["seen_dates"].sort()
        row["publish_count"] = int(row.get("publish_count") or 0) + 1
        row["last_seen_date"] = max(str(row.get("last_seen_date") or ""), run_date)
        row["latest_story_status"] = str(item.get("story_status") or "")
        row["latest_title"] = str(item.get("title") or "")
        for source_type in item.get("source_types") or ([] if not item.get("source_type") else [item.get("source_type")]):
            source_type_value = str(source_type or "").strip()
            if source_type_value and source_type_value not in row["source_types"]:
                row["source_types"].append(source_type_value)
        for source_name in item.get("source_names") or ([] if not item.get("source_name") else [item.get("source_name")]):
            source_name_value = str(source_name or "").strip()
            if source_name_value and source_name_value not in row["source_names"]:
                row["source_names"].append(source_name_value)
        row["max_mention_count"] = max(int(row.get("max_mention_count") or 0), int(item.get("mention_count") or 0))

    payload = {
        "mode": "rss-story-ledger",
        "updated_at": run_date,
        "story_count": len(stories_by_id),
        "stories": sorted(stories_by_id.values(), key=lambda item: str(item.get("last_seen_date") or ""), reverse=True),
    }
    write_json(ledger_path, payload)
    return payload


def build_prefilter_input(
    clustered_payload: Dict[str, Any],
    focus: Dict[str, Any],
    story_history: Dict[str, Any],
    output_path: Path,
) -> Dict[str, Any]:
    history_by_story_id = {
        str(item.get("story_id") or "").strip(): item
        for item in (story_history.get("stories") or [])
        if str(item.get("story_id") or "").strip()
    }
    entries = [
        {
            "id": str(item.get("id") or ""),
            "source_type": str(item.get("source_type") or "rss"),
            "source_name": str(item.get("source_name") or ""),
            "title": str(item.get("title") or ""),
            "tags": list(item.get("tags") or []),
            "story_id": str(item.get("story_id") or ""),
            "story_status": str(item.get("story_status") or ""),
            "duplicate_count": int(item.get("duplicate_count") or 0),
            "history_hint": build_history_hint(item, history_by_story_id),
        }
        for item in (clustered_payload.get("items") or [])
    ]
    payload = {
        "mode": "rss-prefilter",
        "item_count": len(entries),
        "focus": focus,
        "reviewer_prompt": build_prefilter_reviewer_prompt(),
        "reviewer_checklist": build_prefilter_reviewer_checklist(),
        "decision_criteria": build_prefilter_decision_criteria(),
        "reviewer_output_schema": build_prefilter_output_schema(),
        "recent_story_history": list(story_history.get("stories") or []),
        "entries": entries,
    }
    write_json(output_path, payload)
    stage_log("prefilter", "input-written", input_path=str(output_path), item_count=len(entries))
    return payload


def validate_prefilter_results(path: Path, clustered_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = load_json(path)
    items = payload.get("items")
    if not isinstance(items, list):
        fail("prefilter_results.json must contain an 'items' list.")
    raw_ids = {str(entry.get("id") or "") for entry in (clustered_payload.get("items") or [])}
    seen = set()
    for item in items:
        entry_id = str(item.get("id") or "")
        decision = str(item.get("decision") or "")
        if entry_id not in raw_ids:
            fail(f"prefilter_results.json contains unknown id: {entry_id}")
        if decision not in {"keep", "drop", "uncertain"}:
            fail(f"Invalid prefilter decision for {entry_id}: {decision}")
        seen.add(entry_id)
    missing = sorted(raw_ids - seen)
    if missing:
        fail(f"prefilter_results.json is missing decisions for {len(missing)} items.")
    return payload


def build_filter_candidates(clustered_payload: Dict[str, Any], prefilter_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries_by_id = {str(entry.get("id") or ""): dict(entry) for entry in (clustered_payload.get("items") or [])}
    selected = []
    for item in prefilter_payload.get("items", []):
        if str(item.get("decision") or "") not in {"keep", "uncertain"}:
            continue
        entry = entries_by_id.get(str(item.get("id") or ""))
        if entry:
            selected.append(entry)
    if not selected:
        fail("No RSS items advanced to rss-filter. Stopping before digest.")
    return selected


def build_filter_input(
    filter_candidates: List[Dict[str, Any]],
    focus: Dict[str, Any],
    story_history: Dict[str, Any],
    output_path: Path,
) -> Dict[str, Any]:
    history_by_story_id = {
        str(item.get("story_id") or "").strip(): item
        for item in (story_history.get("stories") or [])
        if str(item.get("story_id") or "").strip()
    }
    entries = []
    for item in filter_candidates:
        row = dict(item)
        row["history_hint"] = build_history_hint(row, history_by_story_id)
        entries.append(row)
    payload = {
        "mode": "rss-filter",
        "count": len(entries),
        "focus": focus,
        "reviewer_prompt": build_filter_reviewer_prompt(),
        "reviewer_checklist": build_filter_reviewer_checklist(),
        "decision_criteria": build_filter_decision_criteria(),
        "reviewer_output_schema": build_filter_output_schema(),
        "recent_story_history": list(story_history.get("stories") or []),
        "entries": entries,
    }
    write_json(output_path, payload)
    stage_log("filter", "input-written", input_path=str(output_path), candidate_count=len(entries))
    return payload


def validate_filter_results(path: Path, allowed_ids: List[str]) -> Dict[str, Any]:
    payload = load_json(path)
    items = payload.get("items")
    if not isinstance(items, list):
        fail("filter_results.json must contain an 'items' list.")
    allowed = set(allowed_ids)
    seen = set()
    for item in items:
        entry_id = str(item.get("id") or "")
        if entry_id not in allowed:
            fail(f"filter_results.json contains id outside filter candidate set: {entry_id}")
        seen.add(entry_id)
    missing = sorted(allowed - seen)
    if missing:
        fail(f"filter_results.json is missing decisions for {len(missing)} candidate items.")
    return payload


def auto_prefilter(clustered_payload: Dict[str, Any], focus: Dict[str, Any], output_path: Path) -> Dict[str, Any]:
    items = []
    keywords = [str(item) for item in (focus.get("keywords") or [])]
    exclude_keywords = [str(item) for item in (focus.get("exclude_keywords") or [])]
    for entry in clustered_payload.get("items", []) or []:
        title = str(entry.get("title") or "").strip()
        text = combined_entry_text(entry)
        clean_text = cleaned_entry_body(entry)
        decision = "drop"
        reason = "No title or content signal."
        if looks_like_ad(text, exclude_keywords):
            decision = "drop"
            reason = "Dropped by auto-prefilter because ad/promo keywords were detected."
        elif looks_like_x_promo_or_noise(entry, clean_text):
            decision = "drop"
            reason = "Dropped by auto-prefilter because the X/Twitter item looks promotional or low-signal."
        elif not title:
            decision = "drop"
            reason = "Dropped by auto-prefilter because title is empty."
        elif keywords:
            matches = token_match_count(text, keywords)
            if matches > 0 or has_technical_signal(clean_text):
                decision = "keep"
                reason = (
                    f"Kept by auto-prefilter because {matches} focus keywords matched."
                    if matches > 0
                    else "Kept by auto-prefilter because technical signal was detected."
                )
            else:
                decision = "uncertain"
                reason = "Marked uncertain by auto-prefilter because no focus keywords matched."
        else:
            decision = "keep"
            reason = "Automatic fallback kept titled entry for end-to-end RSS testing."
        items.append({"id": str(entry.get("id") or ""), "decision": decision, "reason": reason})
    payload = {"mode": "rss-prefilter-results", "items": items, "generated_by": "rss-daily-auto-fallback"}
    write_json(output_path, payload)
    stage_log("prefilter", "auto-generated", results_path=str(output_path), item_count=len(items))
    return payload

def infer_domains(entry: Dict[str, Any]) -> List[Dict[str, str]]:
    merged = combined_entry_text(entry)
    result = []
    for slug, hints in DOMAIN_HINTS.items():
        if any(token in merged for token in hints):
            if slug == "agent":
                result.append({"slug": "agent", "name": "Agent"})
            elif slug == "physical-embodied-intelligence":
                result.append({"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"})
            elif slug == "llm-vlm":
                result.append({"slug": "llm-vlm", "name": "LLM/VLM"})
            elif slug == "aigc":
                result.append({"slug": "aigc", "name": "AIGC"})
    if not result:
        lowered = normalize_text(merged)
        if any(token in lowered for token in {"大模型", "多模态", "推理", "transformer", "claude", "openai", "gemini", "token", "算力", "后训练", "模型"}):
            result.append({"slug": "llm-vlm", "name": "LLM/VLM"})
        if any(token in lowered for token in {"机器人", "具身", "机械臂", "robot", "robotics", "manipulation", "无人机", "vla", "world model"}):
            result.append({"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"})
        if any(token in lowered for token in {"视频生成", "图像生成", "扩散", "diffusion", "video generation", "image generation"}):
            result.append({"slug": "aigc", "name": "AIGC"})
        if any(token in lowered for token in {"智能体", "agent", "workflow", "tool use", "claude code", "code agent"}):
            result.append({"slug": "agent", "name": "Agent"})
    if result:
        deduped = []
        seen = set()
        for item in result:
            key = item["slug"]
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped[:2]
    return [{"slug": "uncategorized", "name": "Uncategorized"}]


def auto_filter(
    filter_candidates: List[Dict[str, Any]],
    focus: Dict[str, Any],
    output_path: Path,
    story_history: Dict[str, Any],
) -> Dict[str, Any]:
    items = []
    keywords = [str(item) for item in (focus.get("keywords") or [])]
    exclude_keywords = [str(item) for item in (focus.get("exclude_keywords") or [])]
    seen_story_ids = {
        str(item.get("story_id") or "").strip()
        for item in (story_history.get("stories") or [])
        if str(item.get("story_id") or "").strip()
    }
    for entry in filter_candidates:
        summary = str(entry.get("summary") or "").strip()
        title = str(entry.get("title") or "").strip()
        text = combined_entry_text(entry)
        clean_text = cleaned_entry_body(entry)
        focus_matches = token_match_count(text, keywords)
        include = bool(title)
        reason = "Automatic fallback included titled entry for RSS pipeline testing." if include else "Automatic fallback dropped empty title entry."
        story_id = str(entry.get("story_id") or "")
        story_status = str(entry.get("story_status") or "")
        if looks_like_ad(text, exclude_keywords):
            include = False
            reason = "Dropped by auto-filter because ad/promo keywords were detected."
        elif looks_like_x_promo_or_noise(entry, clean_text):
            include = False
            reason = "Dropped by auto-filter because the X/Twitter item looks promotional or low-signal."
        elif story_id and story_id in seen_story_ids:
            if should_keep_recent_repeat(entry, clean_text):
                include = True
                reason = "Included by auto-filter because this item revisits recent history but still carries strong technical signal."
            else:
                include = False
                reason = "Dropped by auto-filter because this story_id already appeared in recent digest history and is not marked as followup."
        elif keywords and focus_matches <= 0 and not has_technical_signal(clean_text):
            include = False
            reason = "Dropped by auto-filter because no focus keywords matched."
        elif keywords and (focus_matches > 0 or has_technical_signal(clean_text)):
            reason = (
                f"Included by auto-filter because {focus_matches} focus keywords matched."
                if focus_matches > 0
                else "Included by auto-filter because technical signal was detected."
            )
        items.append(
            {
                "id": str(entry.get("id") or ""),
                "include_in_digest": include,
                "domains": infer_domains(entry),
                "one_liner_zh": "",
                "summary_cn": "",
                "reason": reason,
                "title": title,
                "summary": summary,
                "source_type": str(entry.get("source_type") or "rss"),
                "source_name": str(entry.get("source_name") or ""),
                "url": str(entry.get("url") or ""),
                "published_at": str(entry.get("published_at") or ""),
                "canonical_id": str(entry.get("canonical_id") or ""),
                "story_id": story_id,
                "story_status": story_status,
                "content_text": str(entry.get("content_text") or ""),
                "duplicate_count": int(entry.get("duplicate_count") or 0),
                "duplicate_items": list(entry.get("duplicate_items") or []),
            }
        )
    payload = {
        "mode": "rss-filter-results",
        "items": items,
        "generated_by": "rss-daily-auto-fallback",
        "agent_handoff_note": "Replace auto filter results with agent-reviewed results for production-quality digest decisions.",
    }
    write_json(output_path, payload)
    stage_log("filter", "auto-generated", results_path=str(output_path), item_count=len(items))
    return payload


def _auto_one_liner_zh(entry: Dict[str, Any]) -> str:
    existing = str(entry.get("one_liner_zh") or "").strip()
    source_type = str(entry.get("source_type") or "rss").strip().lower()
    if existing and not (source_type == "x" and needs_x_auto_refresh(existing, one_liner=True)):
        if source_type != "wechat" or not needs_wechat_auto_refresh_one_liner(existing, str(entry.get("title") or "")):
            return existing
    title = strip_summary_markup(str(entry.get("title") or ""))
    title = RT_PREFIX_PAT.sub("", title)
    title = " ".join(title.split()).strip()
    if source_type == "x":
        return infer_x_one_liner_zh(entry)
    if source_type == "wechat":
        return infer_wechat_one_liner_zh(entry)
    if not title:
        return ""
    if contains_cjk(title):
        return truncate_text(title, 60)
    prefix_map = {
        "x": "X 动态：",
        "wechat": "微信文章：",
        "arxiv": "论文速览：",
        "bilibili": "视频内容：",
        "rss": "内容速览：",
    }
    prefix = prefix_map.get(source_type, "内容速览：")
    return truncate_text(f"{prefix}{title}", 80)


def _auto_summary_cn(entry: Dict[str, Any]) -> str:
    existing = str(entry.get("summary_cn") or "").strip()
    source_type = str(entry.get("source_type") or "rss").strip().lower()
    if existing and not (source_type == "x" and needs_x_auto_refresh(existing, one_liner=False)):
        if source_type != "wechat" or not needs_wechat_auto_refresh_summary(existing, str(entry.get("title") or "")):
            return existing
    summary = strip_summary_markup(str(entry.get("summary") or ""))
    content = strip_summary_markup(str(entry.get("content_text") or ""))
    title = strip_summary_markup(str(entry.get("title") or ""))
    title = RT_PREFIX_PAT.sub("", title)
    body = summary or content or title
    if not body:
        return ""
    if source_type == "x":
        line = infer_x_one_liner_zh(entry)
        return line if line else "分享了一条值得关注的动态。"
    if source_type == "wechat":
        return infer_wechat_summary_cn(entry)
    if contains_cjk(body):
        return truncate_text(body, 180)
    return truncate_text(f"原文摘要：{body}", 220)


def auto_complete_enrich_payload(enrich_payload: Dict[str, Any], output_path: Path) -> Dict[str, Any]:
    entries = []
    for raw in list(enrich_payload.get("entries") or []):
        entry = dict(raw)
        entry["one_liner_zh"] = _auto_one_liner_zh(entry)
        entry["summary_cn"] = _auto_summary_cn(entry)
        entry["needs_agent_summary"] = not (str(entry.get("one_liner_zh") or "").strip() and str(entry.get("summary_cn") or "").strip())
        entry["agent_summary_prompt"] = ""
        entries.append(entry)
    payload = dict(enrich_payload)
    payload["entries"] = entries
    payload["agent_completion"] = {
        "required": False,
        "task_count": 0,
        "recommended_batch_size": 0,
        "recommended_worker": "rss-daily-auto-workers",
        "tasks": [],
        "note": "Chinese fields were auto-filled for auto-workers mode.",
    }
    write_json(output_path, payload)
    stage_log("enrich", "auto-filled-chinese", output_path=str(output_path), entry_count=len(entries))
    return payload


def run_enrich(filter_payload: Dict[str, Any], enrich_results_path: Path) -> Dict[str, Any]:
    temp_input = enrich_results_path.parent / "enrich_input.json"
    write_json(temp_input, filter_payload)
    stage_log("enrich", "start", input=str(temp_input), output=str(enrich_results_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-enrich" / "rss_enrich.py"),
            "enrich",
            "--input",
            str(temp_input),
            "--output",
            str(enrich_results_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(enrich_results_path)
    agent_completion = payload.get("agent_completion") or {}
    stage_log(
        "enrich",
        "done",
        output_path=str(enrich_results_path),
        entry_count=len(payload.get("entries") or []),
        agent_completion_required=bool(agent_completion.get("required", False)),
        agent_completion_task_count=int(agent_completion.get("task_count", 0) or 0),
    )
    return payload


def build_digest(enrich_results_path: Path, digest_json_path: Path) -> Dict[str, Any]:
    stage_log("digest", "start", input=str(enrich_results_path), output=str(digest_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-digest" / "rss_digest.py"),
            "build",
            "--input",
            str(enrich_results_path),
            "--output",
            str(digest_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(digest_json_path)
    story_count = sum(int(section.get("count") or 0) for section in (payload.get("sections") or []))
    stage_log("digest", "done", output_path=str(digest_json_path), count=story_count)
    return payload


def ensure_publish_digest_date(digest_json_path: Path, digest_date: str) -> None:
    payload = load_json(digest_json_path)
    if str(payload.get("date") or "").strip():
        return
    payload["date"] = digest_date
    write_json(digest_json_path, payload)


def has_remote_publish_config(config: Dict[str, Any]) -> bool:
    publish_config = config.get("publish") or {}
    r2_config = config.get("r2") or config.get("rclone") or {}
    if not isinstance(publish_config, dict) or not isinstance(r2_config, dict):
        return False
    required_r2_keys = ("account_id", "access_key_id", "secret_access_key", "bucket")
    return bool(publish_config.get("remote_prefix")) and all(str(r2_config.get(key) or "").strip() for key in required_r2_keys)


def publish_digest(
    digest_json_path: Path,
    publish_dir: Path,
    digest_date: str,
    *,
    config_path: Path,
    remote_publish: bool,
    allow_historical: bool,
) -> str:
    command = "publish-daily" if remote_publish else "build-daily"
    stage_log(
        "publish",
        "start",
        command=command,
        input=str(digest_json_path),
        output_dir=str(publish_dir),
    )
    ensure_publish_digest_date(digest_json_path, digest_date)
    args = [
        sys.executable,
        str(REPO_ROOT / "skill" / "follow-publish" / "follow_publish.py"),
        command,
        "--input",
        str(digest_json_path),
        "--output-dir",
        str(publish_dir),
        "--config",
        str(config_path),
    ]
    if remote_publish and allow_historical:
        args.append("--allow-historical")
    run_command(args, cwd=REPO_ROOT)
    publish_mode = "remote" if remote_publish else "local"
    stage_log("publish", "done", output_dir=str(publish_dir), mode=publish_mode)
    return publish_mode


def verify_publish(publish_dir: Path, verify_json_path: Path, digest_date: str) -> Dict[str, Any]:
    stage_log("verify", "start", publish_dir=str(publish_dir), output=str(verify_json_path))
    run_command(
        [
            sys.executable,
            str(REPO_ROOT / "skill" / "rss-verify" / "rss_verify.py"),
            "verify",
            "--publish-dir",
            str(publish_dir),
            "--date",
            digest_date,
            "--output",
            str(verify_json_path),
        ],
        cwd=REPO_ROOT,
    )
    payload = load_json(verify_json_path)
    stage_log("verify", "done", verify_json=str(verify_json_path), ok=bool(payload.get("ok", False)))
    return payload


def ensure_agent_completion_done(enrich_payload: Dict[str, Any], enrich_results_path: Path) -> None:
    agent_completion = enrich_payload.get("agent_completion") or {}
    tasks = list(agent_completion.get("tasks") or []) if isinstance(agent_completion, dict) else []
    if tasks:
        fail(
            "rss-enrich reported pending agent completion tasks. "
            f"Complete them and merge one_liner_zh/summary_cn/related_organizations/related_companies/key_people into {enrich_results_path} before rerunning digest/publish. "
            f"Pending tasks: {len(tasks)}"
        )


def command_daily(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    config = load_yaml(config_path)
    run_date = args.date or today_string()
    output_root = Path(args.output_root or DEFAULT_OUTPUT_ROOT)
    run_root = output_root / run_date
    run_root.mkdir(parents=True, exist_ok=True)
    paths = build_paths(run_root, output_root, run_date)
    focus = rss_focus(config)
    rss_config = config.get("rss") or {}
    daily_config = rss_config.get("daily") if isinstance(rss_config, dict) else {}
    history_lookback_days = int((daily_config or {}).get("history_lookback_days", 7) or 7)
    recent_story_history = build_story_history(output_root, run_date, history_lookback_days, paths.story_history_json)
    story_ledger = load_story_ledger(paths.story_ledger_json)
    story_history = build_combined_story_history(recent_story_history, story_ledger, paths.story_history_json)
    collect_runtime = rss_collect_runtime(config)

    stage_log("daily", "start", config=str(config_path), date=run_date, output_root=str(run_root))
    raw_payload = collect_daily(config_path, paths.raw_json)
    if bool(focus.get("strict_date_only", True)):
        raw_payload = filter_items_to_run_date(raw_payload, run_date, paths.raw_json)
    normalize_daily(paths.raw_json, paths.normalized_json)
    fetch_daily(
        paths.normalized_json,
        paths.fetched_json,
        max_workers=collect_runtime["max_workers"],
        request_timeout_seconds=collect_runtime["request_timeout_seconds"],
    )
    dedupe_daily(paths.fetched_json, paths.deduped_json)
    clustered_payload = cluster_daily(paths.deduped_json, paths.clustered_json)

    build_prefilter_input(clustered_payload, focus, story_history, paths.prefilter_input)
    if not paths.prefilter_results.exists():
        if args.auto_workers:
            auto_prefilter(clustered_payload, focus, paths.prefilter_results)
        else:
            stage_log("prefilter", "awaiting-results", input_path=str(paths.prefilter_input), expected_results=str(paths.prefilter_results))
            fail(
                "prefilter_results.json is missing. "
                f"Use {paths.prefilter_input} with the rss-prefilter skill, write results to {paths.prefilter_results}, then rerun. "
                "Or pass --auto-workers for testing."
            )
    prefilter_payload = validate_prefilter_results(paths.prefilter_results, clustered_payload)
    stage_log("prefilter", "results-loaded", results_path=str(paths.prefilter_results), item_count=len(prefilter_payload.get("items") or []))

    filter_candidates = build_filter_candidates(clustered_payload, prefilter_payload)
    build_filter_input(filter_candidates, focus, story_history, paths.filter_input)
    if not paths.filter_results.exists():
        if args.auto_workers:
            auto_filter(filter_candidates, focus, paths.filter_results, story_history)
        else:
            stage_log("filter", "awaiting-results", input_path=str(paths.filter_input), expected_results=str(paths.filter_results))
            fail(
                "filter_results.json is missing. "
                f"Use {paths.filter_input} with the rss-filter skill, write results to {paths.filter_results}, then rerun. "
                "Or pass --auto-workers for testing."
            )
    filter_payload = validate_filter_results(paths.filter_results, [str(entry.get("id") or "") for entry in filter_candidates])
    stage_log("filter", "results-loaded", results_path=str(paths.filter_results), item_count=len(filter_payload.get("items") or []))

    enrich_payload = run_enrich(filter_payload, paths.enrich_results)
    if args.require_agent_enrich:
        ensure_agent_completion_done(enrich_payload, paths.enrich_results)
    elif args.auto_workers:
        enrich_payload = auto_complete_enrich_payload(enrich_payload, paths.enrich_results)
    else:
        stage_log(
            "enrich",
            "agent-completion-deferred",
            output_path=str(paths.enrich_results),
            note="Continuing with empty Chinese fields for pipeline testing. Use --require-agent-enrich to enforce completion.",
        )

    build_digest(paths.enrich_results, paths.digest_json)
    remote_publish = not args.auto_workers and has_remote_publish_config(config)
    publish_mode = publish_digest(
        paths.digest_json,
        paths.publish_dir,
        run_date,
        config_path=config_path,
        remote_publish=remote_publish,
        allow_historical=bool(args.allow_historical_publish),
    )
    verify_payload = verify_publish(paths.publish_dir, paths.verify_json, run_date)
    update_story_ledger(paths.story_ledger_json, load_json(paths.digest_json), run_date)

    print(
        json.dumps(
            {
                "date": run_date,
                "run_root": str(paths.run_root),
                "state_root": str(paths.state_root),
                "raw_json": str(paths.raw_json),
                "normalized_json": str(paths.normalized_json),
                "fetched_json": str(paths.fetched_json),
                "deduped_json": str(paths.deduped_json),
                "clustered_json": str(paths.clustered_json),
                "story_history_json": str(paths.story_history_json),
                "story_ledger_json": str(paths.story_ledger_json),
                "prefilter_input": str(paths.prefilter_input),
                "prefilter_results": str(paths.prefilter_results),
                "filter_input": str(paths.filter_input),
                "filter_results": str(paths.filter_results),
                "enrich_results": str(paths.enrich_results),
                "digest_json": str(paths.digest_json),
                "publish_dir": str(paths.publish_dir),
                "publish_mode": publish_mode,
                "verify_json": str(paths.verify_json),
                "verified": bool(verify_payload.get("ok", False)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rss-daily")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily")
    daily.add_argument("--config")
    daily.add_argument("--date", default=today_string())
    daily.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    daily.add_argument("--auto-workers", action="store_true")
    daily.add_argument("--require-agent-enrich", action="store_true")
    daily.add_argument("--allow-historical-publish", action="store_true")
    daily.set_defaults(func=command_daily)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
