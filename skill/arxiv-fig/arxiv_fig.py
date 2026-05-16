#!/usr/bin/env python3
from __future__ import annotations

"""
arxiv_fig.py - Extract and optionally publish relevant figures from arXiv papers.

Three-level fallback strategy:
  Level 1: arxiv.org/html/{id} -> parse <figure> tags (best: has caption + remote URL)
  Level 2: arxiv.org/e-print/{id} -> download source package -> find image files
  Level 3: arxiv.org/pdf/{id} -> extract embedded images + captions via pdftotext

Usage:
    python arxiv_fig.py <arxiv_id_or_url> [--intent "architecture"]
    python arxiv_fig.py help
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import yaml
from PIL import Image


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_PATH.parents[2]
RCLI_PATH = REPO_ROOT / "skill" / "rcli" / "scripts" / "rcli.py"
INTENT_KEYWORDS_PATH = SKILL_DIR / "intent_keywords.yaml"
DEFAULT_SUGGESTION_LOG_PATH = SKILL_DIR / "keyword_suggestions.jsonl"

HELP_TEXT = """\
arxiv-fig: Extract and optionally publish relevant figures from arXiv papers.

Usage:
    /arxiv-fig <arxiv_id_or_url> --intent "architecture"
    /arxiv-fig <arxiv_id_or_url> --intent "Figure 1"
    /arxiv-fig <arxiv_id_or_url>
    /arxiv-fig help

Arguments:
    arxiv_id_or_url  arXiv ID (2604.20834), abs URL, or PDF URL

Options:
    --intent         Figure intent such as architecture, system, pipeline, Figure 1
    --config-file    FollowHub YAML config path
    --max-results    Max number of matched figures to return
    --suggest-log    Override keyword suggestion log path

Fallback strategy:
    Level 1: HTML version (best quality, has captions, remote URLs)
    Level 2: Source package (local files, may lack captions)
    Level 3: PDF extraction (last resort, embedded images + text captions)
"""

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
IMAGE_DIRS = {"figures", "pics", "fig", "images", "img", "figure"}
LOGO_KEYWORDS = {"logo", "icon", "badge", "banner"}
SOURCE_BONUS = {"html": 3, "arxiv_source": 2, "pdf": 1, "none": 0}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "their",
    "using",
    "used",
    "overview",
    "figure",
    "proposed",
    "method",
    "results",
    "based",
    "over",
    "under",
}


def parse_arxiv_id(raw: str) -> str:
    """Extract arXiv ID from any input format."""
    match = re.search(r"(\d{4}\.\d{4,6})", raw)
    if not match:
        raise ValueError(f"Cannot extract arXiv ID from: {raw}")
    return match.group(1)


def resolve_followhub_config_path(explicit_path: str | None = None) -> Path | None:
    candidates = [
        explicit_path,
        os.environ.get("FOLLOWHUB_CONFIG"),
        os.environ.get("Followhub_Config"),
        str(REPO_ROOT / "config.yaml"),
        "~/.followhub/config.yaml",
    ]
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path
    return None


def load_followhub_config(explicit_path: str | None = None) -> tuple[dict, Path | None]:
    config_path = resolve_followhub_config_path(explicit_path)
    if not config_path:
        return {}, None
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}, config_path


def load_intent_keywords(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    normalized = {}
    for intent_name, values in data.items():
        values = values or {}
        normalized[intent_name] = {
            "aliases": [str(item).lower() for item in values.get("aliases", [])],
            "positive": [str(item).lower() for item in values.get("positive", [])],
            "negative": [str(item).lower() for item in values.get("negative", [])],
        }
    return normalized


def get_arxiv_fig_config(config: dict) -> dict:
    section = config.get("arxiv_fig") or {}
    return {
        "cloudflare_bucket_dir": str(section.get("cloudflare_bucket_dir", "")).strip().strip("/"),
        "max_image_long_side": int(section.get("max_image_long_side", 1600) or 1600),
        "jpeg_quality": int(section.get("jpeg_quality", 82) or 82),
        "low_confidence_threshold": int(section.get("low_confidence_threshold", 12) or 12),
    }


def slugify_text(value: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        return ""
    return slug[:max_length].strip("-")


def clean_caption_text(caption: str) -> str:
    text = (caption or "").strip()
    text = re.sub(r"^(?:figure|fig\.)\s*\d+\s*[:.\-)]?\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def build_paper_dir_name(arxiv_id: str, paper_title: str) -> str:
    title_slug = slugify_text(paper_title, max_length=96)
    if not title_slug:
        return arxiv_id
    return f"{arxiv_id}-{title_slug}"


def build_figure_stem(figure: dict) -> str:
    caption_stem = slugify_text(clean_caption_text(figure.get("caption", "")), max_length=96)
    if caption_stem:
        return caption_stem

    image_path = figure.get("image_path")
    if image_path:
        file_stem = slugify_text(Path(image_path).stem, max_length=96)
        if file_stem:
            return file_stem

    image_url = figure.get("image_url")
    if image_url:
        file_stem = slugify_text(Path(image_url).stem, max_length=96)
        if file_stem:
            return file_stem

    return f"figure-{figure.get('figure_number', 'unknown')}"


def extract_candidate_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    keywords = []
    seen = set()
    for token in tokens:
        if token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords[:12]


def record_keyword_suggestion(
    intent: str,
    figure: dict,
    match_score: int,
    suggestion_log_path: Path = DEFAULT_SUGGESTION_LOG_PATH,
) -> None:
    suggestion_log_path.parent.mkdir(parents=True, exist_ok=True)
    source_text = clean_caption_text(figure.get("caption", ""))
    if not source_text:
        source_text = build_figure_stem(figure).replace("-", " ")

    payload = {
        "intent": intent,
        "figure_number": figure.get("figure_number"),
        "match_score": match_score,
        "source": figure.get("source"),
        "caption": figure.get("caption", ""),
        "suggested_keywords": extract_candidate_keywords(source_text),
    }
    with suggestion_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_title_from_html(html: str) -> str | None:
    meta_match = re.search(
        r'<meta[^>]+name=["\']citation_title["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if meta_match:
        return meta_match.group(1).strip()

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None
    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
    title = re.sub(r"\s*\|\s*arXiv.*$", "", title, flags=re.IGNORECASE)
    return title or None


def fetch_url_text(url: str, timeout: int = 15) -> str | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        response = urllib.request.urlopen(request, timeout=timeout)
        if response.status != 200:
            return None
        return response.read().decode()
    except Exception:
        return None


def fetch_paper_title(arxiv_id: str, html: str | None = None) -> str:
    if html:
        title = extract_title_from_html(html)
        if title:
            return title

    abs_html = fetch_url_text(f"https://arxiv.org/abs/{arxiv_id}")
    if abs_html:
        title = extract_title_from_html(abs_html)
        if title:
            return title

        heading_match = re.search(
            r'<h1[^>]*class=["\']title[^"\']*["\'][^>]*>(.*?)</h1>',
            abs_html,
            re.IGNORECASE | re.DOTALL,
        )
        if heading_match:
            title = re.sub(r"<[^>]+>", "", heading_match.group(1))
            title = re.sub(r"^\s*Title:\s*", "", title)
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                return title

    return arxiv_id


def normalize_intent(intent: str, rules: dict) -> dict:
    text = intent.strip().lower()

    figure_match = re.search(r"(?:figure|fig\.?|图|第)\s*(\d+)", text)
    if figure_match:
        return {
            "kind": "figure_number",
            "name": f"figure-{figure_match.group(1)}",
            "figure_number": int(figure_match.group(1)),
        }

    for intent_name, values in rules.items():
        candidates = [intent_name.lower(), *values.get("aliases", [])]
        if any(candidate and candidate in text for candidate in candidates):
            return {"kind": "keyword", "name": intent_name, "figure_number": None}

    return {"kind": "keyword", "name": "generic", "figure_number": None, "free_text": text}


def split_intents(user_intent: str) -> list[str]:
    if not user_intent:
        return []
    parts = re.split(r"[,，;；|\n]+", user_intent)
    intents = [part.strip() for part in parts if part.strip()]
    return intents or [user_intent.strip()]


def infer_default_max_results(user_intent: str | None, explicit_max_results: int | None) -> int | None:
    if explicit_max_results is not None:
        return explicit_max_results
    intents = split_intents(user_intent or "")
    if len(intents) <= 1:
        return 1
    return None


def score_figure_for_intent(figure: dict, resolved_intent: dict, rules: dict) -> int:
    caption = clean_caption_text(figure.get("caption", "")).lower()
    file_hint = build_figure_stem(figure).replace("-", " ").lower()
    source = figure.get("source", "none")

    if resolved_intent["kind"] == "figure_number":
        if figure.get("figure_number") == resolved_intent["figure_number"]:
            return 200 + SOURCE_BONUS.get(source, 0)
        return -100

    rule = rules.get(resolved_intent["name"], {})
    positive = rule.get("positive", [])
    negative = rule.get("negative", [])
    if resolved_intent["name"] == "generic":
        positive = extract_candidate_keywords(resolved_intent.get("free_text", ""))

    score = SOURCE_BONUS.get(source, 0)
    if caption:
        score += 2

    if resolved_intent["name"] == "main_figure":
        if figure.get("figure_number") == 1:
            score += 12
        elif figure.get("figure_number") == 2:
            score += 5

    for keyword in positive:
        if keyword and keyword in caption:
            score += 12
        if keyword and keyword in file_hint:
            score += 7

    for keyword in negative:
        if keyword and keyword in caption:
            score -= 10
        if keyword and keyword in file_hint:
            score -= 6

    return score


def select_relevant_figures(
    figures: list[dict],
    user_intent: str,
    rules: dict,
    max_results: int | None = None,
) -> list[dict]:
    if not user_intent:
        return [dict(figure) for figure in figures]

    merged: dict[int, dict] = {}

    for raw_intent in split_intents(user_intent):
        resolved_intent = normalize_intent(raw_intent, rules)
        for figure in figures:
            score = score_figure_for_intent(figure, resolved_intent, rules)
            if resolved_intent["kind"] == "figure_number" and score < 100:
                continue
            if resolved_intent["kind"] == "keyword" and score <= 0:
                continue

            figure_number = int(figure.get("figure_number", 0))
            existing = merged.get(figure_number)
            if existing is None:
                figure_copy = dict(figure)
                figure_copy["match_score"] = score
                figure_copy["matched_intent"] = resolved_intent["name"]
                figure_copy["matched_intents"] = [resolved_intent["name"]]
                merged[figure_number] = figure_copy
                continue

            existing.setdefault("matched_intents", [])
            if resolved_intent["name"] not in existing["matched_intents"]:
                existing["matched_intents"].append(resolved_intent["name"])
            if score > existing.get("match_score", 0):
                existing["match_score"] = score
                existing["matched_intent"] = resolved_intent["name"]

    scored = list(merged.values())
    scored.sort(key=lambda item: (item.get("match_score", 0), -item.get("figure_number", 10**6)), reverse=True)
    if max_results is None:
        return scored
    return scored[: max(1, max_results)]


def compress_image_for_upload(
    source_path: Path,
    output_dir: Path,
    max_long_side: int = 1600,
    jpeg_quality: int = 82,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slugify_text(source_path.stem) or 'figure'}.jpg"

    with Image.open(source_path) as image:
        image.load()
        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert("RGB")

        longest_side = max(image.size)
        if longest_side > max_long_side:
            scale = max_long_side / float(longest_side)
            new_size = (
                max(1, int(image.size[0] * scale)),
                max(1, int(image.size[1] * scale)),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        image.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)

    return output_path


def upload_file_via_rcli(src_path: str, storage_key: str, config_path: Path | None) -> dict:
    if not RCLI_PATH.exists():
        raise RuntimeError(f"Missing rcli helper: {RCLI_PATH}")

    cmd = [sys.executable, str(RCLI_PATH), "--json", "copyto", src_path, storage_key]
    if config_path:
        cmd.extend(["--config-file", str(config_path)])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "rcli upload failed")

    payload = json.loads(result.stdout)
    if not payload.get("ok", True):
        raise RuntimeError(payload.get("message", "rcli upload failed"))
    return payload


def finalize_selected_figures(
    figures: list[dict],
    arxiv_id: str,
    paper_title: str,
    config: dict,
    config_path: Path | None,
    upload_func=upload_file_via_rcli,
) -> list[dict]:
    arxiv_fig_config = get_arxiv_fig_config(config)
    bucket_dir = arxiv_fig_config["cloudflare_bucket_dir"]
    paper_dir = build_paper_dir_name(arxiv_id, paper_title)
    finalized = []

    for figure in figures:
        figure_copy = dict(figure)
        figure_copy["paper_dir"] = paper_dir

        image_path = figure_copy.get("image_path")
        if figure_copy.get("image_url") or not image_path or not bucket_dir:
            finalized.append(figure_copy)
            continue

        with tempfile.TemporaryDirectory(prefix="arxiv_fig_upload_") as tmpdir:
            compressed_path = compress_image_for_upload(
                Path(image_path),
                Path(tmpdir),
                max_long_side=arxiv_fig_config["max_image_long_side"],
                jpeg_quality=arxiv_fig_config["jpeg_quality"],
            )
            storage_key = f"{bucket_dir}/{paper_dir}/{build_figure_stem(figure_copy)}.jpg"
            try:
                upload_payload = upload_func(str(compressed_path), storage_key, config_path)
                figure_copy["image_url"] = upload_payload.get("url")
                figure_copy["storage_key"] = upload_payload.get("storage_key", storage_key)
            except Exception as exc:
                figure_copy["upload_error"] = str(exc)

        finalized.append(figure_copy)

    return finalized


def fetch_html(arxiv_id: str):
    """Fetch paper HTML. Returns (html, final_url) or (None, None)."""
    for url in [
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://arxiv.org/html/{arxiv_id}v1",
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            if resp.status == 200:
                return resp.read().decode(), resp.geturl() or url
        except Exception:
            pass
    return None, None


def extract_figures_from_html(html: str, html_url: str):
    """Level 1: Extract figures from HTML <figure> tags."""
    figures_raw = re.findall(r"<figure[^>]*>.*?</figure>", html, re.DOTALL)
    figures = []
    base_url = html_url if html_url.endswith("/") else f"{html_url}/"

    for i, fig in enumerate(figures_raw):
        img = re.search(r'<img[^>]*src="([^"]+)"', fig)
        if not img:
            continue

        cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fig, re.DOTALL)
        cap_text = re.sub(r"<[^>]+>", "", cap.group(1)).strip() if cap else ""

        src = urljoin(base_url, img.group(1).strip())

        figures.append(
            {
                "figure_number": i + 1,
                "caption": cap_text,
                "image_url": src,
                "image_path": None,
                "source": "html",
            }
        )

    return figures


def download_arxiv_source(arxiv_id: str, dest_dir: str) -> bool:
    """Download and extract arXiv source package (tar.gz)."""
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        if resp.status != 200:
            return False

        content = resp.read()
        if len(content) < 100:
            return False

        tar_path = os.path.join(dest_dir, "source.tar.gz")
        with open(tar_path, "wb") as handle:
            handle.write(content)

        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                members = []
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        continue
                    if member.issym() or member.islnk():
                        continue
                    members.append(member)
                tar.extractall(path=dest_dir, members=members)
            return True
        except tarfile.TarError:
            try:
                with tarfile.open(tar_path, "r:") as tar:
                    members = [
                        member
                        for member in tar.getmembers()
                        if not member.name.startswith("/")
                        and ".." not in member.name
                        and not member.issym()
                        and not member.islnk()
                    ]
                    tar.extractall(path=dest_dir, members=members)
                return True
            except Exception:
                return False

    except Exception:
        return False


def convert_pdf_to_png(pdf_path: str, output_dir: str) -> list:
    """Convert a PDF figure file to PNG pages using PyMuPDF."""
    pngs = []
    try:
        import fitz

        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            out_name = f"{Path(pdf_path).stem}_page{page_num + 1}.png"
            out_path = os.path.join(output_dir, out_name)
            pix.save(out_path)
            pngs.append(out_path)
        doc.close()
    except Exception:
        pass
    return pngs


def find_images_in_source(source_dir: str, output_dir: str) -> list:
    """Find image files in the extracted source directory."""
    images = []
    seen_basenames = set()

    for root, _, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        is_image_dir = any(name in rel_root.lower().split("/") for name in IMAGE_DIRS)

        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                continue

            fname_lower = fname.lower()
            if any(keyword in fname_lower for keyword in LOGO_KEYWORDS):
                continue

            fpath = os.path.join(root, fname)

            if not is_image_dir:
                try:
                    if os.path.getsize(fpath) < 5000:
                        continue
                except OSError:
                    continue

            if ext == ".pdf":
                pngs = convert_pdf_to_png(fpath, output_dir)
                for png_path in pngs:
                    png_basename = os.path.basename(png_path)
                    if png_basename not in seen_basenames:
                        seen_basenames.add(png_basename)
                        images.append(png_path)
            elif ext in (".png", ".jpg", ".jpeg", ".eps", ".svg"):
                if fname in seen_basenames:
                    continue
                seen_basenames.add(fname)
                dest = os.path.join(output_dir, fname)
                if os.path.abspath(fpath) != os.path.abspath(dest):
                    shutil.copy2(fpath, dest)
                images.append(dest)

    return images


def extract_balanced_braces(text: str, start: int) -> str:
    """Extract content inside balanced braces starting at position start."""
    if start >= len(text) or text[start] != "{":
        return ""
    depth = 0
    index = start
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
        index += 1
    return text[start + 1 :]


def parse_tex_captions(source_dir: str) -> dict:
    """Parse .tex files to extract \\caption{} and \\includegraphics{} pairs."""
    caption_map = {}

    for root, _, files in os.walk(source_dir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            tex_path = os.path.join(root, fname)
            try:
                with open(tex_path, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
            except Exception:
                continue

            fig_pattern = r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}"
            for fig_match in re.finditer(fig_pattern, content, re.DOTALL):
                block = fig_match.group(1)

                img_name = ""
                img_match = re.search(
                    r"\\includegraphics\s*(?:\[[^\]]*\])?\{(.+?)\}",
                    block,
                )
                if img_match:
                    img_name = os.path.basename(img_match.group(1))

                cap_text = ""
                cap_match = re.search(r"\\caption\s*\{", block)
                if cap_match:
                    brace_start = cap_match.end() - 1
                    cap_content = extract_balanced_braces(block, brace_start)
                    cap_text = re.sub(r"\\[a-zA-Z]+(?:\{[^}]*\})*", "", cap_content)
                    cap_text = re.sub(r"[~%]", " ", cap_text)
                    cap_text = cap_text.strip()[:500]

                if img_name:
                    caption_map[img_name] = cap_text

    return caption_map


def extract_from_arxiv_source(arxiv_id: str) -> list:
    """Level 2: Download arXiv source package and extract image files."""
    output_dir = tempfile.mkdtemp(prefix=f"arxiv_src_{arxiv_id}_")
    source_dir = os.path.join(output_dir, "source")
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    if not download_arxiv_source(arxiv_id, source_dir):
        shutil.rmtree(output_dir, ignore_errors=True)
        return []

    caption_map = parse_tex_captions(source_dir)
    image_files = find_images_in_source(source_dir, images_dir)

    if not image_files:
        shutil.rmtree(output_dir, ignore_errors=True)
        return []

    figures = []
    for i, img_path in enumerate(image_files):
        img_basename = os.path.basename(img_path)
        caption = caption_map.get(img_basename, "")
        if not caption:
            img_stem = Path(img_path).stem
            for tex_name, tex_caption in caption_map.items():
                tex_stem = tex_name.replace(".pdf", "").replace(".png", "")
                if img_stem in tex_name or tex_stem in img_stem:
                    caption = tex_caption
                    break

        figures.append(
            {
                "figure_number": i + 1,
                "caption": caption,
                "image_url": None,
                "image_path": img_path,
                "source": "arxiv_source",
            }
        )

    return figures


def download_pdf(arxiv_id: str, dest_path: str) -> bool:
    """Download paper PDF."""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        if resp.status != 200:
            return False
        with open(dest_path, "wb") as handle:
            handle.write(resp.read())
        return os.path.getsize(dest_path) > 1000
    except Exception:
        return False


def extract_captions_from_pdf_text(pdf_path: str) -> dict:
    """Extract figure captions from PDF text using pdftotext."""
    captions = {}
    try:
        result = subprocess.run(
            ["pdftotext", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return captions

        text = result.stdout

        for match in re.finditer(
            r"(?:^|\n\s*)(?:Figure|Fig\.)\s*(\d+)\s+(.+?)(?=\n\s*\n|\Z)",
            text,
            re.DOTALL,
        ):
            fig_num = int(match.group(1))
            caption_text = match.group(2).strip().replace("\n", " ")[:300]
            if caption_text and len(caption_text) > 10 and fig_num not in captions:
                captions[fig_num] = caption_text

        if len(captions) < 3:
            for match in re.finditer(
                r"(?:Figure|Fig\.)\s*(\d+)\s*[.:)]\s*(.+?)(?=\n\s*\n|\n\s*(?:Figure|Fig\.)\s*\d|\Z)",
                text,
                re.DOTALL,
            ):
                fig_num = int(match.group(1))
                caption_text = match.group(2).strip().replace("\n", " ")[:300]
                if caption_text and len(caption_text) > 10 and fig_num not in captions:
                    captions[fig_num] = caption_text

    except Exception:
        pass
    return captions


def extract_images_from_pdf(pdf_path: str, output_dir: str) -> list:
    """Extract embedded images from PDF using PyMuPDF."""
    images = []
    try:
        import fitz

        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    img_bytes = base_image["image"]
                    img_ext = base_image.get("ext", "png")
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    if width < 200 or height < 200:
                        continue
                    if len(img_bytes) < 5000:
                        continue

                    out_name = f"page{page_num + 1}_fig{img_index + 1}.{img_ext}"
                    out_path = os.path.join(output_dir, out_name)
                    with open(out_path, "wb") as handle:
                        handle.write(img_bytes)

                    images.append(
                        {
                            "page": page_num + 1,
                            "path": out_path,
                            "width": width,
                            "height": height,
                        }
                    )
                except Exception:
                    continue
        doc.close()
    except Exception:
        pass
    return images


def extract_from_pdf(arxiv_id: str) -> list:
    """Level 3: Download PDF and extract embedded images + captions."""
    output_dir = tempfile.mkdtemp(prefix=f"arxiv_pdf_{arxiv_id}_")
    pdf_path = os.path.join(output_dir, f"{arxiv_id}.pdf")

    if not download_pdf(arxiv_id, pdf_path):
        shutil.rmtree(output_dir, ignore_errors=True)
        return []

    captions = extract_captions_from_pdf_text(pdf_path)

    img_dir = os.path.join(output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    extracted = extract_images_from_pdf(pdf_path, img_dir)

    if not extracted:
        try:
            import fitz

            doc = fitz.open(pdf_path)
            for page_num in range(min(len(doc), 30)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150)
                out_path = os.path.join(img_dir, f"page{page_num + 1}.png")
                pix.save(out_path)
                extracted.append(
                    {
                        "page": page_num + 1,
                        "path": out_path,
                        "width": pix.width,
                        "height": pix.height,
                    }
                )
            doc.close()
        except Exception:
            pass

    if not extracted:
        shutil.rmtree(output_dir, ignore_errors=True)
        return []

    figures = []
    for i, img in enumerate(extracted):
        fig_num = i + 1
        figures.append(
            {
                "figure_number": fig_num,
                "caption": captions.get(fig_num, ""),
                "image_url": None,
                "image_path": img["path"],
                "source": "pdf",
            }
        )

    return figures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True, description="Extract relevant figures from arXiv papers.")
    parser.add_argument("arxiv_id_or_url", help="arXiv ID, abstract URL, or PDF URL")
    parser.add_argument("--intent", help='Figure intent such as "architecture", "pipeline", or "Figure 1"')
    parser.add_argument("--config-file", help="Override FollowHub YAML config path")
    parser.add_argument("--max-results", type=int, default=None, help="Max number of matched figures to return")
    parser.add_argument("--suggest-log", help="Override keyword suggestion log path")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv or argv[0].strip().lower() == "help":
        print(HELP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    config, config_path = load_followhub_config(args.config_file)
    arxiv_fig_config = get_arxiv_fig_config(config)
    keyword_rules = load_intent_keywords(INTENT_KEYWORDS_PATH)
    suggestion_log_path = Path(args.suggest_log) if args.suggest_log else DEFAULT_SUGGESTION_LOG_PATH

    arxiv_id = parse_arxiv_id(args.arxiv_id_or_url.strip())
    figures = []
    source = "none"

    html, html_url = fetch_html(arxiv_id)
    if html:
        figures = extract_figures_from_html(html, html_url or f"https://arxiv.org/html/{arxiv_id}")
        if figures:
            source = "html"

    if not figures:
        figures = extract_from_arxiv_source(arxiv_id)
        if figures:
            source = "arxiv_source"

    if not figures:
        figures = extract_from_pdf(arxiv_id)
        if figures:
            source = "pdf"

    paper_title = fetch_paper_title(arxiv_id, html)
    paper_dir = build_paper_dir_name(arxiv_id, paper_title)

    if args.intent:
        max_results = infer_default_max_results(args.intent, args.max_results)
        selected_figures = select_relevant_figures(figures, args.intent, keyword_rules, max_results=max_results)
        selected_figures = finalize_selected_figures(
            selected_figures,
            arxiv_id=arxiv_id,
            paper_title=paper_title,
            config=config,
            config_path=config_path,
        )
        for figure in selected_figures:
            if figure.get("match_score", 0) < arxiv_fig_config["low_confidence_threshold"]:
                record_keyword_suggestion(
                    figure.get("matched_intent", "generic"),
                    figure,
                    figure.get("match_score", 0),
                    suggestion_log_path=suggestion_log_path,
                )
        output_figures = selected_figures
    else:
        output_figures = figures

    output = {
        "arxiv_id": arxiv_id,
        "paper_title": paper_title,
        "paper_dir": paper_dir,
        "source": source,
        "requested_intent": args.intent,
        "candidate_total_figures": len(figures),
        "total_figures": len(output_figures),
        "figures": output_figures,
    }

    if source == "html":
        output["html_url"] = html_url

    if source == "none":
        output["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_id}"

    json_path = REPO_ROOT / f"arxiv_figures_{arxiv_id}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
