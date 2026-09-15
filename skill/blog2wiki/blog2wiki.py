#!/usr/bin/env python3
"""Capture a public blog as immutable raw evidence; analysis stays agent-owned."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen


def http_url(value: str) -> str:
    url = urldefrag(value.strip())[0]
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provide a public HTTP(S) URL without embedded credentials")
    return url


class BlogHTMLParser(HTMLParser):
    """Readable evidence plus media inventory, not a replacement for visual reading."""

    BLOCKS = {"p", "div", "section", "article", "main", "li", "h1", "h2", "h3", "h4", "tr", "figcaption", "br"}
    SKIP = {"script", "style", "nav", "footer", "noscript"}

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.in_body = False
        self.skip_depth = 0
        self.media: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.canonical_url = base_url
        self.published = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
        if self.skip_depth:
            return
        if tag == "body":
            self.in_body = True
        if tag == "title" and not self.in_body:
            self.in_title = True
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag == "link" and attributes.get("rel") == "canonical" and attributes.get("href"):
            self.canonical_url = http_url(urljoin(self.base_url, attributes["href"]))
        if tag == "meta" and attributes.get("property") == "article:published_time":
            self.published = attributes.get("content") or ""
        if tag == "a" and attributes.get("href"):
            self.links.append({"url": urljoin(self.base_url, attributes["href"])})
        if tag in {"img", "video", "source"}:
            for key in ("src", "data-src", "poster"):
                if attributes.get(key):
                    self.media.append({"tag": tag, "attribute": key,
                                       "url": urljoin(self.base_url, attributes[key]),
                                       "description": attributes.get("alt") or attributes.get("aria-label") or ""})

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)

    def readable_text(self) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n\n".join(line for line in lines if line)


def write_immutable(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as output:
            output.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to replace an existing raw snapshot: {path}")


def capture(url: str, wiki_root: Path, slug: str, *, html_file: Path | None = None) -> dict:
    url = http_url(url)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("slug must use lowercase letters, digits, and single hyphens")
    if not (wiki_root / ".wiki-schema.md").is_file():
        raise ValueError("wiki-root must be an existing initialized wiki")
    final_url = url
    charset = "utf-8"
    if html_file:
        raw = html_file.read_bytes()
    else:
        request = Request(url, headers={"User-Agent": "FollowHub-blog2wiki/1.0"})
        with urlopen(request, timeout=30) as response:
            final_url = http_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError(f"Expected HTML, received {content_type}")
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("HTML exceeds 20 MB; use a focused local export")
    parser = BlogHTMLParser(final_url)
    parser.feed(raw.decode(charset, errors="replace"))
    content = parser.readable_text()
    if len(re.sub(r"\s", "", content)) < 120:
        raise ValueError("Insufficient readable HTML; use a browser export or supplied article text")
    digest = hashlib.sha256(raw).hexdigest()
    destination = wiki_root / "raw" / "articles" / slug / digest
    destination.mkdir(parents=True, exist_ok=True)
    write_immutable(destination / "source.html", raw)
    write_immutable(destination / "content.txt", content.encode("utf-8"))
    metadata = {
        "requested_url": url, "resolved_url": final_url, "canonical_url": parser.canonical_url,
        "title": "".join(parser.title_parts).strip(), "published_time": parser.published,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "sha256": digest,
        "media": parser.media, "links": parser.links,
        "capture_method": "local_html" if html_file else "http",
    }
    metadata_path = destination / "metadata.json"
    if not metadata_path.exists():
        write_immutable(metadata_path, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {"ok": True, "slug": slug, "raw_dir": str(destination),
            "raw_file": str(destination / "source.html"), "metadata": str(metadata_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--wiki-root", required=True, type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--html-file", type=Path, help="Existing HTML captured from this URL; no network request")
    args = parser.parse_args()
    try:
        result = capture(args.url, args.wiki_root.resolve(), args.slug, html_file=args.html_file)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"blog2wiki: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
