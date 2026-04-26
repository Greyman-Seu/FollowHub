---
name: arxiv-fig
description: Use when the user wants to find architecture figures, system overview diagrams, or model network structure images from an arXiv paper. Trigger on requests like "find architecture diagram", "extract model structure figure", "get system overview image from paper", or when given an arXiv ID with figure-related keywords.
---

# arxiv-fig

Extract all figures from arXiv papers, then use LLM judgment to match the user's intent against figure captions.

## Three-Level Fallback

```text
Level 1: arxiv.org/html/{id} -> parse <figure> tags (best: caption + remote URL)
    ↓ (no HTML version)
Level 2: arxiv.org/e-print/{id} -> download source package -> find image files
    ↓ (source has no images)
Level 3: arxiv.org/pdf/{id} -> extract embedded images + captions via pdftotext
```

| Level | Source | Caption | Image Location | Quality |
|-------|--------|---------|----------------|---------|
| 1 | HTML | Full caption text | Remote URL (`image_url`) | Best |
| 2 | Source package | May be empty | Local file (`image_path`) | Good |
| 3 | PDF | From `pdftotext` | Local file (`image_path`) | OK |

## Usage

```bash
/arxiv-fig <arxiv_id_or_url>
/arxiv-fig help
```

## Agent Workflow

1. Receive the user's request, such as `找下这篇论文的架构图 2604.20834`.
2. Extract the arXiv ID from the input.
3. Run `python3 {repo_root}/skill/arxiv-fig/arxiv_fig.py "<arxiv_id>"`.
4. Read the JSON output and inspect the `source` field.
5. Use semantic understanding to match the user's intent against captions and file names.
6. Return the relevant figures.

## Intent Matching

| User says | Look for |
|-----------|----------|
| `架构图` / `architecture` | architecture, model structure, framework diagram, proposed method overview |
| `系统图` / `system` | system overview, pipeline, block diagram |
| `模型结构` | model architecture, network structure |
| `主要的图` | usually Figure 1 or the overview figure |
| `pipeline` | pipeline, workflow, sequence diagram |

For Level 2 where captions may be empty, infer from file names such as `arch_v4.png`.

## Running the Script

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "2604.20834"
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "help"
```

## Output Format

```json
{
  "arxiv_id": "2604.20834",
  "source": "html",
  "total_figures": 11,
  "figures": [
    {
      "figure_number": 1,
      "caption": "Figure 1: ...",
      "image_url": "https://arxiv.org/html/2604.20834v1/x1.png",
      "image_path": null,
      "source": "html"
    }
  ]
}
```

- Level 1: `image_url` is set and `image_path` is null.
- Level 2 and 3: `image_url` is null and `image_path` is set.
- Level 2 captions may be empty.
- `source` is one of `html`, `arxiv_source`, `pdf`, or `none`.

## Key Files

| File | Purpose |
|------|---------|
| `arxiv_fig.py` | Core script with 3-level fallback extraction and JSON output |
| `tests/test_arxiv_fig.py` | Repo-local tests for parsing and CLI help |
| `SKILL.md` | Usage and agent responsibilities |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Doing keyword matching inside the script | The script should output all figures; the agent chooses the relevant ones |
| Using ar5iv as fallback | Do not use it |
| Ignoring `image_path` for Level 2 and 3 | Those levels return local files |
| Expecting captions in Level 2 | Use file names when captions are empty |
