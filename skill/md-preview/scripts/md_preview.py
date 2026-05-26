#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tempfile
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1]
    return text


def parse_frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}
    frontmatter = parts[0][4:]
    result: dict[str, object] = {}
    current_key: str | None = None
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_key:
            existing = result.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(stripped[2:].strip().strip('"'))
            continue
        if ":" not in line:
            current_key = None
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        clean_value = value.strip().strip('"')
        result[current_key] = [] if clean_value == "" else clean_value
    return result


def inline_format(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2" />', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def render_markdown(markdown_text: str, title: str) -> str:
    text = strip_frontmatter(markdown_text).replace("\r\n", "\n")
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    in_list = False
    in_table = False
    table_rows: list[list[str]] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{inline_format(' '.join(paragraph).strip())}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def is_table_separator(parts: list[str]) -> bool:
        return all(re.fullmatch(r":?-{3,}:?", part.strip()) for part in parts if part.strip())

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not in_table or not table_rows:
            return
        header = table_rows[0]
        body_rows = table_rows[1:]
        table_html = ["<div class=\"table-container\"><table><thead><tr>"]
        table_html.extend(f"<th>{inline_format(cell)}</th>" for cell in header)
        table_html.append("</tr></thead><tbody>")
        for row in body_rows:
            table_html.append("<tr>")
            table_html.extend(f"<td>{inline_format(cell)}</td>" for cell in row)
            table_html.append("</tr>")
        table_html.append("</tbody></table></div>")
        out.append("".join(table_html))
        in_table = False
        table_rows = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            flush_table()
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            flush_table()
            continue

        image_only_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image_only_match:
            flush_paragraph()
            close_list()
            flush_table()
            alt_text = html.escape(image_only_match.group(1))
            src = html.escape(image_only_match.group(2))
            out.append(f'<figure class="inline-figure"><img alt="{alt_text}" src="{src}" /></figure>')
            continue

        if "|" in stripped and stripped.count("|") >= 2:
            parts = [part.strip() for part in stripped.strip("|").split("|")]
            if parts:
                flush_paragraph()
                close_list()
                if not in_table:
                    in_table = True
                    table_rows = []
                if table_rows and is_table_separator(parts):
                    continue
                table_rows.append(parts)
                continue
        else:
            flush_table()

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            close_list()
            flush_table()
            level = len(heading_match.group(1))
            out.append(f"<h{level}>{inline_format(heading_match.group(2))}</h{level}>")
            continue

        list_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if list_match:
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline_format(list_match.group(1))}</li>")
            continue

        close_list()
        paragraph.append(stripped)

    flush_paragraph()
    close_list()
    flush_table()

    body = "\n".join(out)
    frontmatter = parse_frontmatter(markdown_text)
    source_url = str(frontmatter.get("source_url", "") or "")
    html_url = str(frontmatter.get("html_url", "") or "")
    pdf_url = str(frontmatter.get("pdf_url", "") or "")
    code_url = str(frontmatter.get("code_url", "") or "")
    translation_url = str(frontmatter.get("translation_url", "") or "")
    publish_date = str(frontmatter.get("publish_date", "") or "")
    domain = str(frontmatter.get("domain", "") or "")
    affiliation = str(frontmatter.get("affiliation", "") or "")
    authors = frontmatter.get("authors", [])
    if not isinstance(authors, list):
        authors = []
    keywords = frontmatter.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    images = frontmatter.get("images", [])
    if not isinstance(images, list):
        images = []
    hero_image = images[0] if images and isinstance(images[0], str) and images[0] != "none" else ""

    body = re.sub(
        r"<h2>太长不看</h2>\s*<p>(.*?)</p>",
        r'<section class="callout callout-tldr"><div class="callout-label">TL;DR</div><p>\1</p></section>',
        body,
        count=1,
        flags=re.DOTALL,
    )
    body = re.sub(
        r"<h2>直观理解</h2>\s*<p>(.*?)</p>",
        r'<section class="callout callout-intuition"><div class="callout-label">直观理解</div><p>\1</p></section>',
        body,
        count=1,
        flags=re.DOTALL,
    )
    body = re.sub(
        r"<h2>TL;DR</h2>\s*<p>(.*?)</p>",
        r'<section class="callout callout-tldr"><div class="callout-label">TL;DR</div><p>\1</p></section>',
        body,
        count=1,
        flags=re.DOTALL,
    )
    body = re.sub(
        r"<h2>Intuitive Understanding</h2>\s*<p>(.*?)</p>",
        r'<section class="callout callout-intuition"><div class="callout-label">Intuition</div><p>\1</p></section>',
        body,
        count=1,
        flags=re.DOTALL,
    )

    body = re.sub(r"<h1>.*?</h1>\s*", "", body, count=1, flags=re.DOTALL)

    intro_html = ""
    sections_html = ""
    split_match = re.split(r"(?=<h2>)", body, maxsplit=1)
    if len(split_match) == 2:
        intro_html, sections_blob = split_match
    else:
        intro_html, sections_blob = body, ""

    section_parts = re.findall(r"(<h2>.*?)(?=<h2>|$)", sections_blob, flags=re.DOTALL)
    if section_parts:
        rendered_sections: list[str] = []
        for part in section_parts:
            title_match = re.search(r"<h2>(.*?)</h2>", part, flags=re.DOTALL)
            section_title = title_match.group(1).strip() if title_match else "Section"
            section_body = re.sub(r"^<h2>.*?</h2>\s*", "", part, count=1, flags=re.DOTALL)
            rendered_sections.append(
                f'<details class="paper-card collapsible" open>'
                f'<summary><span>{section_title}</span><span class="summary-chevron">+</span></summary>'
                f'<div class="card-body">{section_body}</div>'
                f'</details>'
            )
        sections_html = "".join(rendered_sections)
    intro_html = f'<section class="paper-intro">{intro_html}</section>' if intro_html.strip() else ""

    hero_meta = []
    if publish_date:
        hero_meta.append(("🗓", html.escape(publish_date), ""))
    if domain:
        hero_meta.append(("🏷", html.escape(domain), ""))
    if source_url:
        hero_meta.append(("📄", "论文地址", html.escape(source_url)))
    if html_url:
        hero_meta.append(("🌐", "HTML", html.escape(html_url)))
    if pdf_url:
        hero_meta.append(("⬇", "PDF", html.escape(pdf_url)))
    if code_url:
        hero_meta.append(("💻", "Code", html.escape(code_url)))
    if translation_url:
        hero_meta.append(("🌏", "中英翻译", html.escape(translation_url)))
    hero_meta_html = "".join(
        f'<li><span class="meta-icon">{icon}</span><a href="{url}" target="_blank" rel="noreferrer">{label}</a></li>' if url else f'<li><span class="meta-icon">{icon}</span><span>{label}</span></li>'
        for icon, label, url in hero_meta
    )
    author_html = ""
    if authors:
        author_html = f'<p class="authors">{" · ".join(html.escape(author) for author in authors)}</p>'
    affiliation_html = ""
    if affiliation:
        affiliation_html = f'<p class="affiliation">{html.escape(affiliation)}</p>'
    keyword_html = ""
    if keywords:
        keyword_html = '<div class="keyword-row">' + "".join(
            f'<span class="keyword-chip">{html.escape(keyword)}</span>' for keyword in keywords if keyword != "none"
        ) + "</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --fg: #1a1a1a;
      --muted: #667085;
      --border: #e5e7eb;
      --accent: #0b67d0;
      --accent-soft: #e8f1fe;
      --accent-soft-2: #eef8f5;
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 16px/1.75 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    }}
    .navbar {{
      background: #fff;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
      position: sticky;
      top: 0;
      z-index: 30;
    }}
    .nav-inner {{
      max-width: 1080px;
      margin: 0 auto;
      height: 60px;
      padding: 0 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .nav-brand {{
      font-size: 22px;
      font-weight: 700;
      color: var(--accent);
      text-decoration: none;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 36px 20px 96px;
    }}
    .paper-shell {{
      background: transparent;
    }}
    .hero {{
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 10px;
      box-shadow: var(--shadow);
      padding: 40px 38px 32px;
      text-align: center;
      margin-bottom: 28px;
    }}
    .eyebrow {{
      margin: 0 0 12px;
      font: 700 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .hero h1 {{
      margin: 0;
      font-size: clamp(2rem, 3vw, 2.75rem);
      line-height: 1.24;
      text-wrap: balance;
    }}
    .authors {{
      margin: 18px 0 0;
      color: var(--muted);
      font-size: 1rem;
      letter-spacing: 0.01em;
    }}
    .affiliation {{
      margin: 10px 0 0;
      color: #98a2b3;
      font-size: 0.92rem;
      line-height: 1.6;
    }}
    .hero-meta {{
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px 14px;
      padding: 0;
      margin: 22px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .hero-meta li {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 999px;
      background: #f8fafc;
      border: 1px solid var(--border);
    }}
    .meta-icon {{
      font-size: 0.95rem;
    }}
    .keyword-row {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px;
      margin-top: 20px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }}
    .keyword-chip {{
      background: var(--accent-soft);
      color: var(--accent);
      padding: 8px 13px;
      border-radius: 999px;
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid rgba(11, 103, 208, 0.12);
    }}
    .content {{
      padding: 0;
    }}
    .paper-intro {{
      margin-bottom: 24px;
    }}
    h1, h2, h3, h4, h5, h6 {{ line-height: 1.22; }}
    h2 {{
      margin: 0 0 18px;
      padding-bottom: 10px;
      border-bottom: 2px solid var(--accent);
      font-size: 1.5rem;
    }}
    p, li {{
      color: var(--fg);
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    ul {{
      padding-left: 1.3rem;
    }}
    li + li {{
      margin-top: 0.45rem;
    }}
    .paper-card {{
      background: #fff;
      border-radius: 10px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
      border: 1px solid var(--border);
    }}
    .collapsible summary {{
      list-style: none;
      cursor: pointer;
      padding: 24px 30px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      font-size: 1.5rem;
      font-weight: 600;
      border-bottom: 2px solid var(--accent);
    }}
    .collapsible summary::-webkit-details-marker {{
      display: none;
    }}
    .summary-chevron {{
      font-size: 1.25rem;
      color: var(--accent);
      line-height: 1;
      transition: transform 0.2s ease;
    }}
    .collapsible[open] .summary-chevron {{
      transform: rotate(45deg);
    }}
    .card-body {{
      padding: 22px 30px 28px;
    }}
    .callout {{
      margin: 0 0 20px;
      padding: 18px 20px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #fff;
      box-shadow: var(--shadow);
    }}
    .callout-label {{
      margin-bottom: 10px;
      font: 700 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent);
    }}
    .callout p {{
      margin: 0;
      font-size: 1rem;
    }}
    .callout-tldr {{
      background: #fff;
    }}
    .callout-intuition {{
      background: #fff;
    }}
    pre {{
      overflow-x: auto;
      background: #f6efe5;
      border-radius: 12px;
      padding: 14px 16px;
      border: 1px solid var(--border);
    }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 12px;
      border: 1px solid var(--border);
      display: block;
      margin: 1rem 0;
    }}
    .inline-figure {{
      margin: 1.2rem 0;
      padding: 14px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #fafafa;
    }}
    .inline-figure img {{
      margin: 0;
      width: 100%;
      background: #fff;
      object-fit: contain;
      border-radius: 12px;
    }}
    .content p em:only-child {{
      display: block;
      margin-top: 0.8rem;
      text-align: center;
      color: var(--muted);
      font-size: 0.92rem;
      font-style: italic;
    }}
    .table-container {{
      overflow-x: auto;
      margin: 1rem 0 1.4rem;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #fff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.96rem;
    }}
    th, td {{
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid rgba(99, 79, 55, 0.1);
      vertical-align: top;
    }}
    th {{
      background: #f8fafc;
      font-weight: 700;
    }}
    @media (max-width: 720px) {{
      main {{
        padding: 18px 12px 64px;
      }}
      .hero {{
        padding: 24px 18px 20px;
      }}
      .paper-card {{
        margin-bottom: 18px;
      }}
      .collapsible summary {{
        padding: 18px 18px;
        font-size: 1.2rem;
      }}
      .card-body {{
        padding: 18px 18px 22px;
      }}
    }}
  </style>
</head>
<body>
  <div class="navbar">
    <div class="nav-inner">
      <a class="nav-brand" href="#">Paper View</a>
    </div>
  </div>
  <main>
    <article class="paper-shell">
      <header class="hero">
        <p class="eyebrow">Paper Digest</p>
        <h1>{html.escape(title)}</h1>
        {author_html}
        {affiliation_html}
        <ul class="hero-meta">{hero_meta_html}</ul>
        {keyword_html}
      </header>
      <div class="content">
        {intro_html}
        {sections_html}
      </div>
    </article>
  </main>
</body>
</html>"""


def derive_title(markdown_path: Path, markdown_text: str) -> str:
    for line in strip_frontmatter(markdown_text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return markdown_path.stem


def render_to_html(input_path: Path, output_dir: Path, title_override: str | None = None) -> Path:
    markdown_text = input_path.read_text(encoding="utf-8")
    title = title_override or derive_title(input_path, markdown_text)
    html_text = render_markdown(markdown_text, title)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"{input_path.stem}.html"
    html_path.write_text(html_text, encoding="utf-8")
    return html_path


def command_render(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        print(f"Input markdown file not found: {input_path}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(
        tempfile.mkdtemp(prefix="md-preview-")
    )
    html_path = render_to_html(input_path, output_dir, args.title)
    print(f"html_path={html_path}")
    print(f"preview_dir={output_dir}")
    return 0


def command_serve(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        print(f"Input markdown file not found: {input_path}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(
        tempfile.mkdtemp(prefix="md-preview-")
    )
    html_path = render_to_html(input_path, output_dir, args.title)
    os.chdir(output_dir)
    server = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    print(f"html_path={html_path}")
    print(f"preview_dir={output_dir}")
    print(f"preview_url=http://{args.host}:{args.port}/{html_path.name}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a markdown file into temporary preview HTML.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render", help="Render markdown into HTML and exit.")
    render_parser.add_argument("--input", required=True, help="Markdown file path")
    render_parser.add_argument("--output-dir", help="Optional output directory")
    render_parser.add_argument("--title", help="Optional HTML title override")
    render_parser.set_defaults(func=command_render)

    serve_parser = subparsers.add_parser("serve", help="Render markdown and start a local HTTP server.")
    serve_parser.add_argument("--input", required=True, help="Markdown file path")
    serve_parser.add_argument("--output-dir", help="Optional output directory")
    serve_parser.add_argument("--title", help="Optional HTML title override")
    serve_parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    serve_parser.add_argument("--port", type=int, default=8766, help="HTTP bind port")
    serve_parser.set_defaults(func=command_serve)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
