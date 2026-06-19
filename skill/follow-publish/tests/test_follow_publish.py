import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "skill" / "follow-publish"
SCRIPT_PATH = SKILL_DIR / "follow_publish.py"
SKILL_PATH = SKILL_DIR / "SKILL.md"
ARXIV_FIXTURE = REPO_ROOT / "skill" / "arxiv-view" / "tests" / "fixtures" / "daily.json"


def load_skill_module():
    assert SCRIPT_PATH.exists(), f"missing skill script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("followhub_follow_publish", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FollowPublishSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_skill_module()

    def test_skill_files_exist(self):
        self.assertTrue(SKILL_PATH.exists())
        self.assertTrue(SCRIPT_PATH.exists())

    def test_help_command_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("follow-publish", result.stdout)
        self.assertIn("build-from-arxiv", result.stdout)
        self.assertIn("publish-daily", result.stdout)

    def test_build_package_writes_manifest_latest_and_sources(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Daily summary.",
                "highlights": ["A", "B"],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:1",
                                "title": "Example Paper",
                                "summary": "Useful summary.",
                                "importance": "high",
                                "one_liner_zh": "一句话总结。",
                                "summary_cn": "中文摘要。",
                                "author_meta": [
                                    {
                                        "name": "Alice",
                                        "affiliations": ["Stanford University"],
                                        "is_first_author": True,
                                        "is_corresponding_author": False,
                                    }
                                ],
                                "related_organizations": ["Stanford University", "OpenAI"],
                                "related_companies": ["OpenAI"],
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/1"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self.module.build_package([digest], output_dir=Path(tmpdir))
            self.assertEqual(payload["latest_date"], "2026-05-02")
            self.assertTrue((Path(tmpdir) / "manifest.json").exists())
            self.assertTrue((Path(tmpdir) / "latest.json").exists())
            self.assertTrue((Path(tmpdir) / "daily" / "2026-05-02.json").exists())
            self.assertTrue((Path(tmpdir) / "sources" / "arxiv.json").exists())
            self.assertTrue((Path(tmpdir) / "sources" / "arxiv-recent.json").exists())
            self.assertTrue((Path(tmpdir) / "sources" / "arxiv-2026-05.json").exists())
            manifest = json.loads((Path(tmpdir) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["latest_date"], "2026-05-02")
            self.assertEqual(manifest["sources"][0]["source"], "arxiv")
            daily_file = json.loads((Path(tmpdir) / "daily" / "2026-05-02.json").read_text(encoding="utf-8"))
            item = daily_file["sections"][0]["items"][0]
            self.assertEqual(item["related_organizations"], ["Stanford University", "OpenAI"])
            self.assertEqual(item["related_companies"], ["OpenAI"])


    def test_validate_digest_does_not_split_author_string(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-03",
                "sections": [
                    {
                        "source_type": "arxiv",
                        "items": [
                            {
                                "id": "arxiv:string-authors",
                                "title": "String Authors",
                                "summary": "Summary",
                                "authors": "Charles Xu, Sergey Levine",
                                "related_organizations": "UC Berkeley",
                            }
                        ],
                    }
                ],
            }
        )

        item = digest["sections"][0]["items"][0]
        self.assertEqual(item["authors"], ["Charles Xu, Sergey Levine"])
        self.assertEqual(item["related_organizations"], ["UC Berkeley"])

    def test_build_package_excludes_non_published_items_from_public_artifacts(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Daily summary.",
                "highlights": ["A"],
                "counts": {"arxiv": 2, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:keep",
                                "title": "Keep",
                                "summary": "保留",
                                "importance": "high",
                                "include_in_follow": True,
                                "one_liner_zh": "一句话总结。",
                                "summary_cn": "中文摘要。",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/keep"}],
                            },
                            {
                                "id": "arxiv:drop",
                                "title": "Drop",
                                "summary": "Should be removed",
                                "importance": "low",
                                "include_in_follow": False,
                                "domains": [{"slug": "uncategorized", "name": "Uncategorized"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/drop"}],
                            },
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_package([digest], output_dir=Path(tmpdir))
            source_file = json.loads((Path(tmpdir) / "sources" / "arxiv.json").read_text(encoding="utf-8"))
            daily_file = json.loads((Path(tmpdir) / "daily" / "2026-05-02.json").read_text(encoding="utf-8"))
            self.assertEqual(source_file["item_count"], 1)
            self.assertEqual(len(source_file["items"]), 1)
            self.assertEqual(source_file["items"][0]["id"], "arxiv:keep")
            self.assertEqual(len(daily_file["sections"][0]["items"]), 1)
            self.assertEqual(daily_file["sections"][0]["items"][0]["id"], "arxiv:keep")

    def test_build_package_deduplicates_same_arxiv_id_across_days_preferring_chinese(self):
        older = self.module.validate_digest(
            {
                "date": "2026-05-04",
                "summary": "Older",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:2605.00244",
                                "title": "Lucid-XR",
                                "summary": "English only",
                                "importance": "medium",
                                "include_in_follow": True,
                                "one_liner_zh": "",
                                "summary_cn": "",
                                "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/2605.00244v1"}],
                            }
                        ],
                    }
                ],
            }
        )
        newer = self.module.validate_digest(
            {
                "date": "2026-05-05",
                "summary": "Newer",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:2605.00244",
                                "title": "Lucid-XR",
                                "summary": "中文版本",
                                "importance": "medium",
                                "include_in_follow": True,
                                "one_liner_zh": "一句话总结。",
                                "summary_cn": "中文摘要。",
                                "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/2605.00244"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_package([newer, older], output_dir=Path(tmpdir))
            source_file = json.loads((Path(tmpdir) / "sources" / "arxiv.json").read_text(encoding="utf-8"))
            matches = [item for item in source_file["items"] if item["id"] == "arxiv:2605.00244"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["date"], "2026-05-05")
            self.assertEqual(matches[0]["summary_cn"], "中文摘要。")

    def test_build_package_keeps_published_arxiv_items_without_chinese_summary(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Daily summary.",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:missing-zh",
                                "title": "Missing zh",
                                "summary": "English only",
                                "importance": "medium",
                                "include_in_follow": True,
                                "one_liner_zh": "",
                                "summary_cn": "",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/missing"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            self.module.build_package([digest], output_dir=Path(tmpdir))
            source_file = json.loads((Path(tmpdir) / "sources" / "arxiv.json").read_text(encoding="utf-8"))
            self.assertEqual(source_file["item_count"], 1)
            self.assertEqual(source_file["items"][0]["id"], "arxiv:missing-zh")

    def test_merge_digests_merges_same_day_sections_by_source_and_id(self):
        existing = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Old summary",
                "highlights": ["old"],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:1",
                                "title": "Paper A",
                                "summary": "Old A",
                                "importance": "medium",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://a"}],
                            }
                        ],
                    }
                ],
            }
        )
        incoming = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "New summary",
                "highlights": ["new"],
                "counts": {"arxiv": 1, "wechat": 1, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:1",
                                "title": "Paper A",
                                "summary": "New A",
                                "importance": "high",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://a2"}],
                            }
                        ],
                    },
                    {
                        "source_type": "wechat",
                        "title": "WeChat",
                        "items": [
                            {
                                "id": "wechat:1",
                                "title": "Article B",
                                "summary": "B",
                                "importance": "medium",
                                "domains": [{"slug": "agent", "name": "Agent"}],
                                "links": [{"label": "Article", "href": "https://b"}],
                            }
                        ],
                    },
                ],
            }
        )
        merged = self.module.merge_digests(existing, incoming)
        self.assertEqual(
            merged["summary"],
            "2026-05-02 Follow daily selected 1 arXiv paper(s) and 1 WeChat item(s).",
        )
        self.assertEqual(merged["counts"]["arxiv"], 1)
        self.assertEqual(merged["counts"]["wechat"], 1)
        self.assertEqual(len(merged["sections"]), 2)
        arxiv_section = [section for section in merged["sections"] if section["source_type"] == "arxiv"][0]
        self.assertEqual(arxiv_section["items"][0]["summary"], "New A")

    def test_merge_digests_recomputes_summary_and_highlights_for_multi_source_day(self):
        existing = self.module.validate_digest(
            {
                "date": "2026-05-26",
                "summary": "2026-05-26 arXiv daily selected 1 papers for follow-up.",
                "highlights": ["arxiv only"],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:1",
                                "title": "Arxiv A",
                                "summary": "Arxiv summary",
                                "importance": "high",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [],
                            }
                        ],
                    }
                ],
            }
        )
        incoming = self.module.validate_digest(
            {
                "date": "2026-05-26",
                "summary": "Selected 1 RSS stories for today.",
                "highlights": ["wechat only"],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "WeChat",
                        "items": [
                            {
                                "id": "wechat:1",
                                "title": "Wechat A",
                                "summary": "Wechat summary",
                                "importance": "medium",
                                "domains": [{"slug": "agent", "name": "Agent"}],
                                "links": [],
                            }
                        ],
                    }
                ],
            }
        )

        merged = self.module.merge_digests(existing, incoming)
        self.assertEqual(
            merged["summary"],
            "2026-05-26 Follow daily selected 1 arXiv paper(s) and 1 WeChat item(s).",
        )
        self.assertEqual(merged["counts"]["arxiv"], 1)
        self.assertEqual(merged["counts"]["wechat"], 1)
        self.assertTrue(any("Arxiv A" in item for item in merged["highlights"]))
        self.assertTrue(any("Wechat A" in item for item in merged["highlights"]))

    def test_build_digest_highlights_preserves_multi_source_coverage(self):
        sections = [
            {
                "source_type": "arxiv",
                "title": "arXiv",
                "items": [
                    {"id": "arxiv:1", "title": "Arxiv A", "summary": "A", "importance": "high", "overall_score": 3.0},
                    {"id": "arxiv:2", "title": "Arxiv B", "summary": "B", "importance": "high", "overall_score": 2.8},
                ],
            },
            {
                "source_type": "wechat",
                "title": "WeChat",
                "items": [
                    {"id": "wechat:1", "title": "Wechat A", "summary": "W", "importance": "medium", "overall_score": 0.0},
                ],
            },
        ]
        highlights = self.module.build_digest_highlights_from_sections(sections)
        self.assertTrue(any("Arxiv A" in item for item in highlights))
        self.assertTrue(any("Wechat A" in item for item in highlights))

    def test_build_digest_summary_includes_x_counts(self):
        summary = self.module.build_digest_summary(
            "2026-06-18",
            [
                {"source_type": "x", "count": 47},
                {"source_type": "wechat", "count": 3},
            ],
            {"arxiv": 0, "wechat": 3, "x": 47, "bilibili": 0},
            "fallback summary",
        )
        self.assertEqual(
            summary,
            "2026-06-18 Follow daily selected 3 WeChat item(s) and 47 X / Twitter item(s).",
        )

    def test_build_package_can_sync_page_data_dir(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-01",
                "summary": "Digest.",
                "highlights": [],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "WeChat",
                        "items": [
                            {
                                "id": "wechat:1",
                                "title": "Article",
                                "summary": "Summary",
                                "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz",
                                "importance": "medium",
                                "domains": [{"slug": "agent", "name": "Agent"}],
                                "links": [{"label": "Mirror", "href": "https://example.com"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as page_dir:
            self.module.build_package(
                [digest],
                output_dir=Path(tmpdir),
                page_data_dir=Path(page_dir) / "follow",
            )
            self.assertTrue((Path(page_dir) / "follow" / "manifest.json").exists())
            self.assertTrue((Path(page_dir) / "follow" / "sources" / "wechat.json").exists())
            wechat_source = json.loads((Path(tmpdir) / "sources" / "wechat.json").read_text(encoding="utf-8"))
            first_item = wechat_source["items"][0]
            self.assertEqual(first_item["url"], "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz")
            hrefs = [link["href"] for link in first_item["links"]]
            self.assertIn("https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz", hrefs)

    def test_build_digest_from_arxiv_input_generates_arxiv_digest(self):
        digest = self.module.build_digest_from_arxiv_input(
            ARXIV_FIXTURE,
            self.module.deepcopy(self.module.DEFAULT_DOMAIN_CONFIG),
        )
        self.assertEqual(digest["sections"][0]["source_type"], "arxiv")
        self.assertEqual(digest["counts"]["arxiv"], 2)
        first_item = digest["sections"][0]["items"][0]
        self.assertTrue(first_item["domains"])
        self.assertTrue(first_item["links"])
        self.assertLessEqual(len(first_item["domains"]), 2)
        self.assertIn("authors", first_item)
        self.assertIn("abstract_en", first_item)
        self.assertIn("one_liner_zh", first_item)
        self.assertIn("summary_cn", first_item)

    def test_infer_domains_for_vla_arxiv_items_is_not_overly_broad(self):
        domain_config = self.module.deepcopy(self.module.DEFAULT_DOMAIN_CONFIG)
        long_horizon_item = {
            "title": "Long-Horizon Manipulation via Trace-Conditioned VLA Planning",
            "one_liner_zh": "把短视 VLA 执行扩展到长程操作规划。",
            "summary_cn": "",
            "abstract_en": "A VLA planning system for long-horizon manipulation.",
            "matched_keywords": ["VLA", "vision-language-action"],
            "categories": ["cs.RO"],
        }
        corridor_item = {
            "title": "CorridorVLA: Explicit Spatial Constraints for Generative Action Heads",
            "one_liner_zh": "",
            "summary_cn": "",
            "abstract_en": "Generative action head with explicit spatial anchors for VLA models.",
            "matched_keywords": ["VLA"],
            "categories": ["cs.RO", "cs.AI"],
        }

        long_horizon_domains = self.module.infer_domains_for_arxiv_item(long_horizon_item, domain_config)
        corridor_domains = self.module.infer_domains_for_arxiv_item(corridor_item, domain_config)

        self.assertEqual(
            [item["slug"] for item in long_horizon_domains],
            ["uncategorized"]
        )
        self.assertEqual(
            [item["slug"] for item in corridor_domains],
            ["uncategorized"]
        )

    def test_cli_build_from_arxiv_writes_daily_digest_and_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "build-from-arxiv",
                    "--input",
                    str(ARXIV_FIXTURE),
                    "--output-dir",
                    str(tmpdir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue((Path(tmpdir) / "daily-digest.json").exists())
            self.assertTrue((Path(tmpdir) / "manifest.json").exists())
            source_file = json.loads((Path(tmpdir) / "sources" / "arxiv.json").read_text(encoding="utf-8"))
            self.assertEqual(source_file["source"], "arxiv")
            self.assertEqual(source_file["item_count"], 2)

    def test_rebuild_index_command_reads_daily_directory(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-03",
                "summary": "Digest.",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:3",
                                "title": "Paper",
                                "summary": "Summary",
                                "importance": "high",
                                "one_liner_zh": "一句话总结。",
                                "summary_cn": "中文摘要。",
                                "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/3"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as daily_dir, tempfile.TemporaryDirectory() as out_dir:
            self.module.save_json(Path(daily_dir) / "2026-05-03.json", digest)
            payload = self.module.rebuild_index_command(
                daily_dir=Path(daily_dir),
                output_dir=Path(out_dir),
            )
            self.assertEqual(payload["latest_date"], "2026-05-03")
            self.assertTrue((Path(out_dir) / "manifest.json").exists())

    def test_publish_daily_command_merges_remote_daily_and_uploads(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Incoming digest",
                "highlights": ["incoming"],
                "counts": {"arxiv": 0, "wechat": 1, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "wechat",
                        "title": "WeChat",
                        "items": [
                            {
                                "id": "wechat:2",
                                "title": "Incoming article",
                                "summary": "Hello",
                                "importance": "medium",
                                "domains": [{"slug": "agent", "name": "Agent"}],
                                "links": [{"label": "Article", "href": "https://example.com/incoming"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            digest_path = Path(tmpdir) / "incoming.json"
            self.module.save_json(digest_path, digest)

            original_load_rcli = self.module.load_rcli_module
            original_fetch_remote = self.module.fetch_remote_json
            original_upload = self.module.upload_artifacts_with_rcli
            try:
                class FakeRcliModule:
                    @staticmethod
                    def resolve_config_path(_explicit):
                        return Path('/tmp/fake-followhub-config.yaml')

                self.module.load_rcli_module = lambda: FakeRcliModule()
                self.module.fetch_remote_json = lambda _module, prefix, key: (
                    {
                        "date": "2026-05-02",
                        "summary": "Remote digest",
                        "highlights": ["remote"],
                        "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                        "sections": [
                            {
                                "source_type": "arxiv",
                                "title": "arXiv",
                                "items": [
                                    {
                                        "id": "arxiv:1",
                                        "title": "Remote paper",
                                        "summary": "Remote summary",
                                        "importance": "high",
                                        "one_liner_zh": "远端一句话总结。",
                                        "summary_cn": "远端中文摘要。",
                                        "domains": [{"slug": "llm-vlm", "name": "LLM/VLM"}],
                                        "links": [{"label": "Abs", "href": "https://arxiv.org/abs/1"}],
                                    }
                                ],
                            }
                        ],
                    }
                    if key == "daily/2026-05-02.json"
                    else {"days": [{"date": "2026-05-02"}]}
                    if key == "manifest.json"
                    else None
                )
                def fake_upload(_module, _config_path, local_dir, remote_prefix, include_paths=None):
                    paths = sorted(include_paths or [path.relative_to(local_dir).as_posix() for path in local_dir.rglob("*") if path.is_file()])
                    return [f"{remote_prefix}/{path}" for path in paths]

                self.module.upload_artifacts_with_rcli = fake_upload
                payload = self.module.publish_daily_command(
                    input_paths=[digest_path],
                    remote_prefix="follow",
                    output_dir=Path(tmpdir) / "out",
                    allow_historical=True,
                )
            finally:
                self.module.load_rcli_module = original_load_rcli
                self.module.fetch_remote_json = original_fetch_remote
                self.module.upload_artifacts_with_rcli = original_upload

            merged_daily = json.loads((Path(tmpdir) / "out" / "daily" / "2026-05-02.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["merged_date"], "2026-05-02")
            self.assertIn("follow/manifest.json", payload["uploaded"])
            self.assertEqual(len(merged_daily["sections"]), 2)
            self.assertEqual(merged_daily["counts"]["arxiv"], 1)
            self.assertEqual(merged_daily["counts"]["wechat"], 1)

    def test_publish_daily_command_normal_mode_uploads_only_incoming_daily(self):
        today = self.module.datetime.now().strftime("%Y-%m-%d")
        digest = self.module.validate_digest(
            {
                "date": today,
                "summary": "Incoming digest",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:today",
                                "title": "Today paper",
                                "summary": "Summary",
                                "importance": "medium",
                                "one_liner_zh": "今日一句话总结。",
                                "summary_cn": "今日中文摘要。",
                                "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/today"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            digest_path = Path(tmpdir) / "incoming.json"
            self.module.save_json(digest_path, digest)

            original_load_rcli = self.module.load_rcli_module
            original_fetch_remote = self.module.fetch_remote_json
            original_upload = self.module.upload_artifacts_with_rcli
            captured = {}
            try:
                class FakeRcliModule:
                    @staticmethod
                    def resolve_config_path(_explicit):
                        return Path('/tmp/fake-followhub-config.yaml')

                self.module.load_rcli_module = lambda: FakeRcliModule()

                def fake_fetch(_module, prefix, key):
                    if key == "manifest.json":
                        return {"days": [{"date": today}, {"date": "2026-05-01"}]}
                    if key == f"daily/{today}.json":
                        return None
                    if key == "daily/2026-05-01.json":
                        return self.module.validate_digest(
                            {
                                "date": "2026-05-01",
                                "summary": "Old digest",
                                "highlights": [],
                                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                                "sections": [
                                    {
                                        "source_type": "arxiv",
                                        "title": "arXiv",
                                        "items": [
                                            {
                                                "id": "arxiv:old",
                                                "title": "Old paper",
                                                "summary": "Summary",
                                                "importance": "low",
                                                "one_liner_zh": "旧的一句话总结。",
                                                "summary_cn": "旧的中文摘要。",
                                                "domains": [{"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}],
                                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/old"}],
                                            }
                                        ],
                                    }
                                ],
                            }
                        )
                    return None

                self.module.fetch_remote_json = fake_fetch

                def fake_upload(_module, _config_path, local_dir, remote_prefix, include_paths=None):
                    captured["include_paths"] = sorted(include_paths or [])
                    return [f"{remote_prefix}/{path}" for path in captured["include_paths"]]

                self.module.upload_artifacts_with_rcli = fake_upload
                payload = self.module.publish_daily_command(
                    input_paths=[digest_path],
                    remote_prefix="follow",
                    output_dir=Path(tmpdir) / "out",
                )
            finally:
                self.module.load_rcli_module = original_load_rcli
                self.module.fetch_remote_json = original_fetch_remote
                self.module.upload_artifacts_with_rcli = original_upload

            self.assertIn(f"daily/{today}.json", captured["include_paths"])
            self.assertNotIn("daily/2026-05-01.json", captured["include_paths"])
            self.assertIn(f"follow/daily/{today}.json", payload["uploaded"])

    def test_publish_daily_command_rejects_historical_date_without_override(self):
        digest = self.module.validate_digest(
            {
                "date": "2026-05-02",
                "summary": "Incoming digest",
                "highlights": [],
                "counts": {"arxiv": 1, "wechat": 0, "x": 0, "bilibili": 0},
                "sections": [
                    {
                        "source_type": "arxiv",
                        "title": "arXiv",
                        "items": [
                            {
                                "id": "arxiv:9",
                                "title": "Paper",
                                "summary": "Summary",
                                "importance": "high",
                                "domains": [{"slug": "uncategorized", "name": "Uncategorized"}],
                                "links": [{"label": "Abs", "href": "https://arxiv.org/abs/9"}],
                            }
                        ],
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            digest_path = Path(tmpdir) / "incoming.json"
            self.module.save_json(digest_path, digest)
            with self.assertRaises(ValueError):
                self.module.publish_daily_command(
                    input_paths=[digest_path],
                    remote_prefix="follow",
                    output_dir=Path(tmpdir) / "out",
                )


if __name__ == "__main__":
    unittest.main()
