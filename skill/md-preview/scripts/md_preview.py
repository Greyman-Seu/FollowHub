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


def inline_format(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2" />', text)
    return text


def render_markdown(markdown_text: str, title: str) -> str:
    text = strip_frontmatter(markdown_text).replace("\r\n", "\n")
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    in_list = False
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

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
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
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            close_list()
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

    body = "\n".join(out)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8f6f1;
      --panel: #fffdf8;
      --fg: #1f1b16;
      --border: #e7dfd3;
      --accent: #8a5a2b;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 16px/1.75 Georgia, "Noto Serif SC", serif;
    }}
    main {{
      max-width: 900px;
      margin: 0 auto;
      padding: 40px 20px 80px;
    }}
    article {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 32px;
      box-shadow: 0 18px 50px rgba(31, 27, 22, 0.06);
    }}
    h1, h2, h3, h4, h5, h6 {{ line-height: 1.25; }}
    a {{ color: var(--accent); }}
    pre {{
      overflow-x: auto;
      background: #f3efe8;
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
  </style>
</head>
<body>
  <main>
    <article>
      {body}
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
