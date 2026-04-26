#!/usr/bin/env python3
"""
arxiv_fig.py - Extract all figures from arXiv papers.

Three-level fallback strategy:
  Level 1: arxiv.org/html/{id} -> parse <figure> tags (best: has caption + remote URL)
  Level 2: arxiv.org/e-print/{id} -> download source package -> find image files
  Level 3: arxiv.org/pdf/{id} -> extract embedded images + captions via pdftotext

Usage:
    python arxiv_fig.py <arxiv_id_or_url>
    python arxiv_fig.py help
"""

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

HELP_TEXT = """\
arxiv-fig: Extract all figures from arXiv papers.

Usage:
    /arxiv-fig <arxiv_id_or_url>
    /arxiv-fig help

Arguments:
    arxiv_id_or_url  arXiv ID (2604.20834), abs URL, or PDF URL

Fallback strategy:
    Level 1: HTML version (best quality, has captions, remote URLs)
    Level 2: Source package (local files, may lack captions)
    Level 3: PDF extraction (last resort, embedded images + text captions)

Examples:
    /arxiv-fig 2604.20834
    /arxiv-fig https://arxiv.org/abs/2604.20347
    /arxiv-fig help
"""

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
IMAGE_DIRS = {"figures", "pics", "fig", "images", "img", "figure"}
LOGO_KEYWORDS = {"logo", "icon", "badge", "banner"}


def parse_arxiv_id(raw: str) -> str:
    """Extract arXiv ID from any input format."""
    match = re.search(r"(\d{4}\.\d{4,6})", raw)
    if not match:
        raise ValueError(f"Cannot extract arXiv ID from: {raw}")
    return match.group(1)


def fetch_html(arxiv_id: str):
    """Fetch paper HTML from arxiv.org. Returns (html, url) or (None, None)."""
    for url in [
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://arxiv.org/html/{arxiv_id}v1",
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            if resp.status == 200:
                return resp.read().decode(), url
        except Exception:
            pass
    return None, None


def extract_figures_from_html(html: str, arxiv_id: str):
    """Level 1: Extract figures from HTML <figure> tags."""
    del arxiv_id
    figures_raw = re.findall(r"<figure[^>]*>.*?</figure>", html, re.DOTALL)
    figures = []

    for i, fig in enumerate(figures_raw):
        img = re.search(r'<img[^>]*src="([^"]+)"', fig)
        if not img:
            continue

        cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fig, re.DOTALL)
        cap_text = re.sub(r"<[^>]+>", "", cap.group(1)).strip() if cap else ""

        src = img.group(1)
        if not src.startswith("http"):
            src = f"https://arxiv.org/html/{src}"

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


def main():
    if len(sys.argv) < 2 or sys.argv[1].strip().lower() == "help":
        print(HELP_TEXT)
        sys.exit(0)

    raw = sys.argv[1].strip()
    arxiv_id = parse_arxiv_id(raw)

    figures = []
    source = "none"

    html, html_url = fetch_html(arxiv_id)
    if html:
        figures = extract_figures_from_html(html, arxiv_id)
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

    output = {
        "arxiv_id": arxiv_id,
        "source": source,
        "total_figures": len(figures),
        "figures": figures,
    }

    if source == "html":
        output["html_url"] = html_url

    if source == "none":
        output["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_id}"

    json_path = f"arxiv_figures_{arxiv_id}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
