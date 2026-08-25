import importlib.util
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


class DailySuccessEvaluationTest(unittest.TestCase):
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

    @mock.patch.object(runner.subprocess, "run")
    def test_lark_notification_uses_bot_chat_message(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="{}", stderr="")
        result = runner.send_lark_message(
            lark_cli="/opt/lark-cli",
            chat_id="oc_test",
            message="done",
            idempotency_key="followhub-20260826-success",
        )
        self.assertTrue(result["ok"])
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
            Path("/srv/FollowHub"), Path("/opt/codex"), Path("/srv/FollowHub/followhub.yaml")
        )
        self.assertIn("WorkingDirectory=/srv/FollowHub", service)
        self.assertIn("FOLLOWHUB_CONFIG=/srv/FollowHub/followhub.yaml", service)
        self.assertIn("TimeoutStartSec=1h50min", service)

    def test_service_passes_notification_and_bridge_context(self):
        service = installer.build_service_unit(
            Path("/srv/FollowHub"),
            Path("/opt/codex"),
            Path("/srv/FollowHub/followhub.yaml"),
            lark_cli=Path("/opt/lark-cli"),
            notify_chat_id="oc_test",
            summary_url="https://tenstep.top/follow/",
            channel_environment={
                "LARK_CHANNEL": "1",
                "LARK_CHANNEL_PROFILE": "daily-profile",
            },
        )
        self.assertIn("--notify-chat-id oc_test", service)
        self.assertIn("--summary-url https://tenstep.top/follow/", service)
        self.assertIn('Environment="LARK_CHANNEL=1"', service)
        self.assertIn('Environment="LARK_CHANNEL_PROFILE=daily-profile"', service)


if __name__ == "__main__":
    unittest.main()
