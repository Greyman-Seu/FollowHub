import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "wiki_sync_page.py"
SPEC = importlib.util.spec_from_file_location("wiki_sync_page", MODULE_PATH)
wiki_sync_page = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = wiki_sync_page
SPEC.loader.exec_module(wiki_sync_page)


class WikiSyncPageTests(unittest.TestCase):
    def test_source_uses_explicit_hero_date_and_normalized_domain(self):
        note = """---
title: "Example Paper"
slug: "example-paper"
source_type: "paper"
source_url: "https://example.com/paper"
date: "2026-09-02"
domains:
  - "Physical/Embodied Intelligence"
related_companies: []
hero_image: "https://example.com/hero.png"
---
# Example Paper

## 太长不看

Example.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "example-paper.md"
            path.write_text(note, encoding="utf-8")
            source = wiki_sync_page.parse_note_source(path)

        self.assertEqual(source.heroImage, "https://example.com/hero.png")
        self.assertEqual(source.publishDate, "2026-09-02")
        self.assertEqual(source.primaryDomainSlug, "physical-embodied-intelligence")
        self.assertEqual(source.relatedCompanies, [])

    def test_command_sync_slug_mode_keeps_single_source_scope(self):
        with tempfile.TemporaryDirectory() as wiki_dir, tempfile.TemporaryDirectory() as page_dir:
            wiki_root = Path(wiki_dir)
            page_root = Path(page_dir)
            source_dir = wiki_root / "wiki" / "sources"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "motus2-a-self-evolving-general-world-model-for-dexterous-manipulation.md").write_text(
                """---
title: "Motus2: A Self-Evolving General World Model for Dexterous Manipulation"
slug: "motus2-a-self-evolving-general-world-model-for-dexterous-manipulation"
source_type: "paper"
source_url: "https://arxiv.org/abs/2608.30237"
date: "2026-08-31"
hero_image: "https://example.com/hero.png"
---
# Motus2

## 太长不看

Example.
""",
                encoding="utf-8",
            )
            (wiki_root / "wiki").mkdir(parents=True, exist_ok=True)
            (wiki_root / "wiki" / "graph-data.json").write_text("{}", encoding="utf-8")
            (wiki_root / "wiki" / "topics").mkdir(parents=True, exist_ok=True)
            (wiki_root / "wiki" / "synthesis").mkdir(parents=True, exist_ok=True)

            args = type("Args", (), {"config": None, "wiki_root": str(wiki_root), "page_root": str(page_root), "slug": "motus2-a-self-evolving-general-world-model-for-dexterous-manipulation", "mode": "sync"})()
            rc = wiki_sync_page.command_sync(args)

            self.assertEqual(rc, 0)
            self.assertTrue((page_root / "src/data/generated/wiki-sync/source/motus2-a-self-evolving-general-world-model-for-dexterous-manipulation.json").is_file())
            self.assertTrue((page_root / "src/data/generated/wiki-sync/sources.json").is_file())
            self.assertFalse((page_root / "src/data/generated/wiki-sync/topics.json").is_file())
            self.assertFalse((page_root / "src/data/generated/wiki-sync/synthesis.json").is_file())


if __name__ == "__main__":
    unittest.main()
