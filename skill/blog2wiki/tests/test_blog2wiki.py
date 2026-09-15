import importlib.util
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location("blog2wiki", Path(__file__).resolve().parents[1] / "blog2wiki.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

HTML = ('<html><head><title>Robot blog</title><link rel="canonical" href="./model/">'
        '<meta property="article:published_time" content="2026-09"></head><body>'
        '<nav>Navigation</nav><article><h1>Model</h1><p>' + 'Human demonstrations drive a policy. ' * 8 +
        '</p><img src="image.png" alt="Architecture"><video poster="demo.jpg">'
        '<source data-src="demo.mp4"></video><script>secret_script_text</script>'
        '<svg><title>Diagram title</title></svg></article></body></html>')


class BlogCaptureTests(unittest.TestCase):
    def test_text_and_lazy_media_keep_source_context(self):
        parser = MODULE.BlogHTMLParser("https://example.org/blog/")
        parser.feed(HTML)
        self.assertNotIn("Navigation", parser.readable_text())
        self.assertNotIn("secret_script_text", parser.readable_text())
        self.assertIn("Human demonstrations", parser.readable_text())
        self.assertEqual(parser.published, "2026-09")
        self.assertEqual("".join(parser.title_parts), "Robot blog")
        self.assertEqual(parser.canonical_url, "https://example.org/blog/model/")
        self.assertEqual([item["url"] for item in parser.media], [
            "https://example.org/blog/image.png", "https://example.org/blog/demo.jpg",
            "https://example.org/blog/demo.mp4"])

    def test_snapshots_are_reused_and_changed_sources_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".wiki-schema.md").touch()
            html = root / "input.html"
            html.write_text(HTML)
            first = MODULE.capture("https://example.org/blog/", root, "model", html_file=html)
            metadata = Path(first["metadata"]).read_bytes()
            again = MODULE.capture("https://example.org/blog/", root, "model", html_file=html)
            self.assertEqual(first, again)
            self.assertEqual(Path(first["metadata"]).read_bytes(), metadata)
            html.write_text(HTML.replace("Model", "Model 2"))
            newer = MODULE.capture("https://example.org/blog/", root, "model", html_file=html)
            self.assertNotEqual(first["raw_dir"], newer["raw_dir"])
            self.assertEqual(Path(first["raw_file"]).read_text(), HTML)

    def test_http_redirect_sets_relative_asset_base(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://example.org/new/"
        response.headers = Message()
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.read.return_value = HTML.encode()
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "urlopen", return_value=response):
            root = Path(tmp)
            (root / ".wiki-schema.md").touch()
            result = MODULE.capture("https://example.org/old", root, "model")
            metadata = json.loads(Path(result["metadata"]).read_text())
            self.assertEqual(metadata["media"][0]["url"], "https://example.org/new/image.png")

    def test_rejects_empty_extraction_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".wiki-schema.md").touch()
            html = root / "empty.html"
            html.write_text("<html><script>render()</script></html>")
            for url, slug in [("file:///etc/passwd", "model"),
                              ("https://user:pass@example.org", "model"),
                              ("https://example.org", "../model"),
                              ("https://example.org", "model")]:
                with self.subTest(url=url, slug=slug), self.assertRaises(ValueError):
                    MODULE.capture(url, root, slug, html_file=html)
            self.assertFalse((root / "raw").exists())


if __name__ == "__main__":
    unittest.main()
