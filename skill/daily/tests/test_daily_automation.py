import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def load_module(name: str, filename: str):
    path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = load_module("followhub_daily_checker_test", "check_daily_success.py")
installer = load_module("followhub_daily_installer_test", "install_scheduled_daily.py")
runner = load_module("followhub_daily_runner_test", "run_scheduled_daily.py")


def item(item_id, source, date):
    return {
        "id": item_id,
        "source_type": source,
        "date": date,
        "title": item_id,
        "summary": item_id,
        "importance": "medium",
    }


def digest(date, counts):
    sections = []
    for source, count in counts.items():
        if count <= 0:
            continue
        items = [item("{0}:{1}".format(source, index), source, date) for index in range(count)]
        sections.append(
            {
                "source_type": source,
                "title": source,
                "count": count,
                "items": items,
            }
        )
    return {"date": date, "counts": counts, "sections": sections}


def write_valid_rss_artifacts(repo, run_date):
    (repo / "rss-daily-output" / run_date / "fetch").mkdir(parents=True)
    (repo / "rss-collect-output").mkdir(parents=True)
    (repo / "rss-daily-output" / run_date / "verify.json").write_text(
        json.dumps({"ok": True, "content_checks": {"story_count": 1}}),
        encoding="utf-8",
    )
    (repo / "rss-daily-output" / run_date / "daily-digest.json").write_text(
        json.dumps(digest(run_date, {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0})),
        encoding="utf-8",
    )
    (repo / "rss-collect-output" / "{0}-raw.json".format(run_date)).write_text(
        json.dumps(
            {"sources": [{"type": "wechat", "status": "ok", "item_count": 1}]}
        ),
        encoding="utf-8",
    )
    (repo / "rss-daily-output" / run_date / "fetch" / "fetched_items.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "wechat:0",
                        "source_type": "wechat",
                        "fetch_status": "fetched-html",
                        "title": "标题",
                        "summary": "摘要",
                        "content_text": "这是一段已验证的微信正文内容。",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class DailySuccessEvaluationTest(unittest.TestCase):
    def test_arxiv_schedule_uses_weekday_boundaries(self):
        self.assertTrue(checker.arxiv_required_for_date("2026-08-28"))
        self.assertFalse(checker.arxiv_required_for_date("2026-08-29"))
        self.assertFalse(checker.arxiv_required_for_date("2026-08-30"))
        self.assertTrue(checker.arxiv_required_for_date("2026-08-31"))

    def test_weekend_local_counts_ignore_missing_or_failed_arxiv_verification(self):
        for run_date, write_failed_arxiv in (
            ("2026-08-29", False),
            ("2026-08-30", True),
        ):
            with self.subTest(run_date=run_date), tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir)
                write_valid_rss_artifacts(repo, run_date)
                if write_failed_arxiv:
                    arxiv_output = repo / "arxiv-daily-output" / run_date
                    arxiv_output.mkdir(parents=True)
                    (arxiv_output / "verify.json").write_text(
                        json.dumps(
                            {
                                "ok": False,
                                "daily_item_count": 99,
                                "blocker": "Official arXiv listing date does not match.",
                            }
                        ),
                        encoding="utf-8",
                    )

                result = checker.expected_local_counts(repo, run_date)

                self.assertTrue(result["ok"])
                self.assertEqual(0, result["counts"]["arxiv"])
                self.assertEqual(["arxiv"], result["skipped_sources"])

    def test_weekday_local_counts_still_require_arxiv_verification(self):
        run_date = "2026-08-31"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            write_valid_rss_artifacts(repo, run_date)

            result = checker.expected_local_counts(repo, run_date)

        self.assertFalse(result["ok"])
        self.assertEqual("missing local verification artifacts", result["reason"])
        self.assertIn(
            "arxiv-daily-output/{0}/verify.json".format(run_date),
            result["missing"][0],
        )

    def test_weekend_local_counts_reject_arxiv_items(self):
        run_date = "2026-08-29"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            write_valid_rss_artifacts(repo, run_date)
            digest_path = repo / "rss-daily-output" / run_date / "daily-digest.json"
            payload = json.loads(digest_path.read_text(encoding="utf-8"))
            payload["sections"].append(
                {
                    "source_type": "arxiv",
                    "title": "arxiv",
                    "count": 1,
                    "items": [item("arxiv:unexpected", "arxiv", run_date)],
                }
            )
            digest_path.write_text(json.dumps(payload), encoding="utf-8")

            result = checker.expected_local_counts(repo, run_date)

        self.assertFalse(result["ok"])
        self.assertEqual("weekend RSS digest contains arXiv items", result["reason"])
        self.assertEqual(["arxiv"], result["skipped_sources"])

    def test_all_x_sources_failing_is_unhealthy(self):
        health = checker.summarize_collection_health(
            {
                "sources": [
                    {
                        "type": "x",
                        "status": "error",
                        "error": "403 Client Error: Forbidden",
                        "item_count": 0,
                    },
                    {
                        "type": "x",
                        "status": "error",
                        "error": "Connection timed out",
                        "item_count": 0,
                    },
                ]
            }
        )
        self.assertEqual(0, health["x"]["ok"])
        self.assertEqual(2, health["x"]["error"])
        self.assertEqual({"forbidden": 1, "timeout": 1}, health["x"]["error_kinds"])

    def test_matching_remote_payloads_succeed(self):
        run_date = "2026-08-26"
        counts = {"arxiv": 3, "wechat": 2, "x": 0, "bilibili": 0}
        payload = digest(run_date, counts)
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=counts,
            daily=payload,
            latest=payload,
            source_payloads={
                "arxiv": {"items": payload["sections"][0]["items"]},
                "wechat": {"items": payload["sections"][1]["items"]},
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(5, result["total_count"])

    def test_expected_local_counts_can_ignore_x_unavailable(self):
        run_date = "2026-08-26"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "arxiv-daily-output" / run_date).mkdir(parents=True)
            (repo / "rss-daily-output" / run_date / "fetch").mkdir(parents=True)
            (repo / "rss-collect-output").mkdir(parents=True)

            (repo / "arxiv-daily-output" / run_date / "verify.json").write_text(
                json.dumps({"ok": True, "daily_item_count": 2, "incomplete_summary_ids": []}),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "verify.json").write_text(
                json.dumps({"ok": True, "content_checks": {"story_count": 1}}),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "daily-digest.json").write_text(
                json.dumps(
                    {
                        "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                        "sections": [
                            {
                                "source_type": "wechat",
                                "title": "wechat",
                                "count": 1,
                                "items": [
                                    {
                                        "id": "wechat:1",
                                        "source_type": "wechat",
                                        "date": run_date,
                                        "title": "标题",
                                        "summary": "摘要",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (repo / "rss-collect-output" / "{0}-raw.json".format(run_date)).write_text(
                json.dumps(
                    {
                        "sources": [
                            {"type": "wechat", "status": "ok", "item_count": 1},
                            {"type": "x", "status": "error", "error": "410 Client Error: Gone", "item_count": 0},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "fetch" / "fetched_items.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "wechat:1",
                                "source_type": "wechat",
                                "fetch_status": "fetched-html",
                                "title": "标题",
                                "summary": "摘要",
                                "content_text": "这是一段足够长的微信正文内容，用来通过已验证正文检查。",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = checker.expected_local_counts(
                repo,
                run_date,
                allow_unavailable_sources=["x"],
            )

            (repo / "arxiv-daily-output" / run_date / "verify.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "daily_item_count": 0,
                        "incomplete_summary_ids": [],
                        "blocker": "Official arXiv listing is not available yet.",
                    }
                ),
                encoding="utf-8",
            )
            pending_result = checker.expected_local_counts(
                repo,
                run_date,
                allow_unavailable_sources=["x"],
            )

        self.assertTrue(result["ok"])
        self.assertEqual(["x"], result["ignored_unavailable_sources"])
        self.assertFalse(pending_result["ok"])
        self.assertIn("Official arXiv listing", pending_result["reason"])
        self.assertEqual({"gone": 1}, pending_result["collection_health"]["x"]["error_kinds"])
        self.assertEqual(["x"], pending_result["ignored_unavailable_sources"])

        message = runner.build_failure_message(
            run_date,
            pending_result,
            "https://tenstep.top/follow/",
        )
        self.assertIn("0/1", message)
        self.assertIn("410 1", message)
        self.assertIn("按配置已忽略", message)

    def test_expected_local_counts_rejects_wechat_fallback_only_publish(self):
        run_date = "2026-08-26"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "arxiv-daily-output" / run_date).mkdir(parents=True)
            (repo / "rss-daily-output" / run_date / "fetch").mkdir(parents=True)
            (repo / "rss-collect-output").mkdir(parents=True)

            (repo / "arxiv-daily-output" / run_date / "verify.json").write_text(
                json.dumps({"ok": True, "daily_item_count": 2, "incomplete_summary_ids": []}),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "verify.json").write_text(
                json.dumps({"ok": True, "content_checks": {"story_count": 1}}),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "daily-digest.json").write_text(
                json.dumps(
                    {
                        "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                        "sections": [
                            {
                                "source_type": "wechat",
                                "title": "wechat",
                                "count": 1,
                                "items": [
                                    {
                                        "id": "wechat:1",
                                        "source_type": "wechat",
                                        "date": run_date,
                                        "title": "微信标题",
                                        "summary": "摘要",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (repo / "rss-collect-output" / "{0}-raw.json".format(run_date)).write_text(
                json.dumps({"sources": [{"type": "wechat", "status": "ok", "item_count": 1}]}),
                encoding="utf-8",
            )
            (repo / "rss-daily-output" / run_date / "fetch" / "fetched_items.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "wechat:1",
                                "source_type": "wechat",
                                "fetch_status": "fallback-blocked",
                                "title": "微信标题",
                                "summary": "摘要",
                                "content_text": "摘要",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = checker.expected_local_counts(repo, run_date)

        self.assertFalse(result["ok"])
        self.assertIn("WeChat", result["reason"])
        self.assertEqual(0, result["fetch_health"]["wechat"]["verified_body_count"])

    def test_missing_same_day_source_update_fails(self):
        run_date = "2026-08-26"
        counts = {"arxiv": 1, "wechat": 1, "x": 0, "bilibili": 0}
        payload = digest(run_date, counts)
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=counts,
            daily=payload,
            latest=payload,
            source_payloads={
                "arxiv": {"items": payload["sections"][0]["items"]},
                "wechat": {"items": []},
            },
        )
        self.assertFalse(result["ok"])
        self.assertEqual("remote source count mismatch", result["reason"])

    def test_weekend_remote_payload_accepts_empty_arxiv_section(self):
        run_date = "2026-08-29"
        expected_counts = {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0}
        unexpected_payload = digest(run_date, expected_counts)
        unexpected_payload["sections"].append(
            {
                "source_type": "arxiv",
                "title": "arxiv",
                "count": 0,
                "items": [],
            }
        )
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=expected_counts,
            daily=unexpected_payload,
            latest=unexpected_payload,
            source_payloads={
                "arxiv": {"items": []},
                "wechat": {"items": unexpected_payload["sections"][0]["items"]},
            },
            skipped_sources=["arxiv"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["source_today_counts"]["arxiv"])

    def test_weekend_remote_payload_rejects_same_day_arxiv_source_item(self):
        run_date = "2026-08-29"
        expected_counts = {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0}
        payload = digest(run_date, expected_counts)
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=expected_counts,
            daily=payload,
            latest=payload,
            source_payloads={
                "arxiv": {"items": [item("arxiv:unexpected", "arxiv", run_date)]},
                "wechat": {"items": payload["sections"][0]["items"]},
            },
            skipped_sources=["arxiv"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual("remote source count mismatch", result["reason"])
        self.assertEqual("arxiv", result["source"])

    def test_weekend_remote_payload_accepts_no_same_day_arxiv_source_items(self):
        run_date = "2026-08-29"
        expected_counts = {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0}
        payload = digest(run_date, expected_counts)
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=expected_counts,
            daily=payload,
            latest=payload,
            source_payloads={
                "arxiv": {"items": [item("arxiv:old", "arxiv", "2026-08-28")]},
                "wechat": {"items": payload["sections"][0]["items"]},
            },
            skipped_sources=["arxiv"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["source_today_counts"]["arxiv"])

    def test_section_count_mismatch_fails(self):
        run_date = "2026-08-26"
        counts = {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0}
        payload = digest(run_date, counts)
        payload["sections"][0]["count"] = 2
        result = checker.evaluate_remote_payloads(
            run_date=run_date,
            expected_counts=counts,
            daily=payload,
            latest=payload,
            source_payloads={"arxiv": {"items": payload["sections"][0]["items"]}},
        )
        self.assertFalse(result["ok"])
        self.assertIn("section count mismatch", result["reason"])


class ScheduledRunnerTest(unittest.TestCase):
    def test_codex_command_is_ephemeral_and_noninteractive(self):
        command = runner.build_codex_command(
            codex_bin="/opt/codex",
            repo=Path("/tmp/followhub"),
            output_message_path=Path("/tmp/message.txt"),
        )
        self.assertIn("--ephemeral", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertEqual("-", command[-1])

    def test_prompt_carries_requested_date(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            prompt_path = Path(temporary_dir) / "prompt.md"
            prompt_path.write_text("Run daily.", encoding="utf-8")
            prompt = runner.build_prompt(prompt_path, "2026-08-26")
        self.assertIn("2026-08-26", prompt)
        self.assertIn("Run daily.", prompt)

    def test_prompt_marks_scheduled_run_as_unattended(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            prompt_path = Path(temporary_dir) / "prompt.md"
            prompt_path.write_text("Delegate via standalone workers.", encoding="utf-8")
            prompt = runner.build_prompt(prompt_path, "2026-08-26")
        self.assertIn("2026-08-26", prompt)
        self.assertIn("standalone workers", prompt)

    def test_weekend_prompt_runs_rss_only(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            prompt_path = Path(temporary_dir) / "prompt.md"
            prompt_path.write_text("Follow the injected date strategy.", encoding="utf-8")
            prompt = runner.build_prompt(prompt_path, "2026-08-29")
        self.assertIn("只运行 RSS", prompt)
        self.assertIn("不要启动、重试、校验或发布 arXiv", prompt)
        self.assertNotIn("这是工作日", prompt)

    def test_weekday_prompt_runs_both_pipelines(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            prompt_path = Path(temporary_dir) / "prompt.md"
            prompt_path.write_text("Follow the injected date strategy.", encoding="utf-8")
            prompt = runner.build_prompt(prompt_path, "2026-08-31")
        self.assertIn("这是工作日", prompt)
        self.assertIn("运行 arXiv 和 RSS 两条生产流水线", prompt)
        self.assertNotIn("只运行 RSS", prompt)

    def test_success_message_contains_counts_and_link(self):
        message = runner.build_success_message(
            "2026-08-26",
            {
                "counts": {"arxiv": 3, "wechat": 2, "x": 1, "bilibili": 0},
                "total_count": 6,
                "collection_health": {"x": {"total": 3, "ok": 2, "error": 1}},
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("共 6 条", message)
        self.assertIn("X/Twitter 1", message)
        self.assertIn("https://tenstep.top/follow/", message)

    def test_weekend_success_message_reports_arxiv_as_skipped(self):
        message = runner.build_success_message(
            "2026-08-29",
            {
                "counts": {"arxiv": 0, "wechat": 2, "x": 0, "bilibili": 0},
                "total_count": 2,
                "skipped_sources": ["arxiv"],
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("arXiv：周末按计划跳过", message)

    def test_failure_message_explains_x_outage(self):
        message = runner.build_failure_message(
            "2026-08-26",
            {
                "reason": "X/Twitter RSS collection is unavailable",
                "collection_health": {
                    "x": {
                        "total": 99,
                        "ok": 0,
                        "error": 99,
                        "error_kinds": {"dns": 42, "timeout": 38, "forbidden": 19},
                    }
                },
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("截至 23:00", message)
        self.assertIn("0/99", message)
        self.assertIn("DNS 42", message)

    def test_failure_message_explains_wechat_fetch_fallback(self):
        message = runner.build_failure_message(
            "2026-08-26",
            {
                "reason": "Published WeChat items appear to rely only on title/summary fallback",
                "fetch_health": {
                    "wechat": {
                        "item_count": 4,
                        "verified_body_count": 0,
                        "fallback_only_count": 4,
                        "fetch_status_counts": {"fallback-blocked": 4},
                    }
                },
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("微信正文抓取", message)
        self.assertIn("仅回退 4", message)
        self.assertIn("fallback-blocked 4", message)

    def test_pending_message_mentions_retry(self):
        message = runner.build_pending_message(
            "2026-08-26",
            {
                "reason": "missing local verification artifacts",
                "skipped_sources": ["arxiv"],
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("仍在重试", message)
        self.assertIn("下一次定时触发", message)
        self.assertIn("arXiv：周末按计划跳过", message)

    def test_weekend_failure_message_reports_arxiv_as_skipped(self):
        message = runner.build_failure_message(
            "2026-08-29",
            {
                "reason": "RSS verification did not pass",
                "skipped_sources": ["arxiv"],
            },
            "https://tenstep.top/follow/",
        )
        self.assertIn("arXiv：周末按计划跳过", message)

    def test_notification_idempotency_key_changes_with_message(self):
        first = runner.build_notification_idempotency_key(
            "2026-08-26", "success", "message a"
        )
        second = runner.build_notification_idempotency_key(
            "2026-08-26", "success", "message b"
        )
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("followhub-20260826-success-"))

    @mock.patch.object(runner.subprocess, "run")
    def test_lark_notification_uses_bot_chat_message(self, run):
        run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps({"data": {"message_id": "om_test"}}),
            stderr="",
        )
        result = runner.send_lark_message(
            lark_cli="/opt/lark-cli",
            chat_id="oc_test",
            message="done",
            idempotency_key="followhub-20260826-success",
        )
        self.assertTrue(result["ok"])
        self.assertEqual("om_test", result["message_id"])
        command = run.call_args.args[0]
        self.assertEqual("/opt/lark-cli", command[0])
        self.assertIn("oc_test", command)
        self.assertIn("--as", command)
        self.assertIn("bot", command)


class SystemdUnitTest(unittest.TestCase):
    def test_timer_has_two_hour_checks_from_seven(self):
        timer = installer.build_timer_unit()
        for hour in installer.RUN_HOURS:
            self.assertIn(
                "OnCalendar=*-*-* {0:02d}:00:00 Asia/Shanghai".format(hour), timer
            )
        self.assertIn("Persistent=true", timer)

    def test_service_uses_exact_repo_and_config(self):
        service = installer.build_service_unit(
            Path("/srv/FollowHub"),
            Path("/opt/codex"),
            Path("/srv/FollowHub/followhub.yaml"),
            node_bin=Path("/opt/node-v20/bin/node"),
        )
        self.assertIn("WorkingDirectory=/srv/FollowHub", service)
        self.assertIn("FOLLOWHUB_CONFIG=/srv/FollowHub/followhub.yaml", service)
        self.assertIn("PATH=/opt/node-v20/bin:/usr/local/sbin", service)
        self.assertIn("TimeoutStartSec=1h50min", service)

    def test_service_passes_notification_and_bridge_context(self):
        service = installer.build_service_unit(
            Path("/srv/FollowHub"),
            Path("/opt/codex"),
            Path("/srv/FollowHub/followhub.yaml"),
            node_bin=Path("/opt/node-v20/bin/node"),
            lark_cli=Path("/opt/lark-cli"),
            notify_chat_id="oc_test",
            summary_url="https://tenstep.top/follow/",
            allow_unavailable_sources=["x"],
            notify_pending_once=True,
            channel_environment={
                "LARK_CHANNEL": "1",
                "LARK_CHANNEL_PROFILE": "daily-profile",
            },
        )
        self.assertIn("--notify-chat-id oc_test", service)
        self.assertIn("--summary-url https://tenstep.top/follow/", service)
        self.assertIn("--allow-unavailable-source x", service)
        self.assertIn("--notify-pending-once", service)
        self.assertIn('Environment="LARK_CHANNEL=1"', service)
        self.assertIn('Environment="LARK_CHANNEL_PROFILE=daily-profile"', service)


if __name__ == "__main__":
    unittest.main()
