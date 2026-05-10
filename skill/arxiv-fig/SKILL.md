---
name: arxiv-fig
description: Use when the user wants to find architecture figures, system overview diagrams, or model network structure images from an arXiv paper. Trigger on requests like "find architecture diagram", "extract model structure figure", "get system overview image from paper", or when given an arXiv ID with figure-related keywords.
---

# arxiv-fig

Extract candidate figures from arXiv papers, score them against the user's intent, and only upload the matched local figures when FollowHub R2 is configured.

## User-Facing Use

This is a skill-first workflow.

The user should speak naturally, for example:

- `找这篇论文的架构图 2604.20834`
- `把这篇 arxiv 的 system 图找出来`
- `找 Figure 1`
- `找 pipeline 图`

The user does not need to provide CLI flags or command syntax.
The agent is responsible for turning the request into an internal intent such as `architecture`, `system`, `pipeline`, or `Figure 1`.

## Invocation Model

- This skill is meant to be installed into Codex / Claude and invoked by an agent.
- The Python CLI is the extraction tool surface that the agent calls internally.
- The CLI is not intended to be the primary human-facing interface.

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
| 2 | Source package | May be empty | Local file first, optional uploaded URL after matching | Good |
| 3 | PDF | From `pdftotext` | Local file first, optional uploaded URL after matching | OK |

## Agent Entry Pattern

```bash
/arxiv-fig <arxiv_id_or_url> --intent "architecture"
/arxiv-fig <arxiv_id_or_url> --intent "Figure 1"
/arxiv-fig help
```

These command examples are implementation details for the agent, not the preferred user interface.

## Agent Workflow

1. Receive the user's request, such as `找下这篇论文的架构图 2604.20834`.
2. Extract the arXiv ID from the input.
3. Convert the request into a short intent string such as `architecture`, `system`, `pipeline`, or `Figure 1`.
4. Run `python3 {repo_root}/skill/arxiv-fig/arxiv_fig.py "<arxiv_id>" --intent "<intent>"`.
5. Read the JSON output.
6. Return the matched figures.

Do not ask the user to rephrase their request into CLI arguments unless the paper ID itself is missing or ambiguous.
For a single intent such as `架构图`, `主图`, `system 图`, or `Figure 1`, return the single highest-confidence figure by default.
Only return multiple figures when the user explicitly asks for multiple, or when the request contains multiple intents.

## Intent Matching

| User says | Look for |
|-----------|----------|
| `架构图` / `architecture` | architecture, model structure, framework diagram, proposed method overview |
| `系统图` / `system` | system overview, pipeline, block diagram |
| `模型结构` | model architecture, network structure |
| `主要的图` | usually Figure 1 or the overview figure |
| `pipeline` | pipeline, workflow, sequence diagram |

The script already does rule-based scoring with `intent_keywords.yaml`. For Level 2 where captions may be empty, it also uses file names such as `arch_v4.png`.

## Upload Behavior

- HTML figures already have `image_url`; do not re-upload them.
- Source/PDF figures are extracted locally first.
- Only the matched local figures are uploaded.
- When `--intent` contains multiple keywords, the script matches each keyword, merges the results, and uploads all unique matches.
- Images are resized before upload so they stay readable while saving Cloudflare quota.
- If `arxiv_fig.cloudflare_bucket_dir` is missing in YAML, keep the local `image_path` and do not upload.
- If upload fails, return the local path and include `upload_error`.
- Use `--max-results` only when you explicitly want truncation.

## Config

Expected YAML sections:

```yaml
rclone:
  account_id: ...
  access_key_id: ...
  secret_access_key: ...
  bucket: followhub
  public_base_url: https://followhub.tenstep.top

arxiv_fig:
  cloudflare_bucket_dir: papers
  max_image_long_side: 1600
  jpeg_quality: 82
  low_confidence_threshold: 12
```

The upload path pattern is:

```text
<cloudflare_bucket_dir>/<arxiv_id>-<slugified_title>/<caption_slug>.jpg
```

## Agent Tool Surface

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "2604.20834" --intent "architecture"
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "2604.20834" --intent "Figure 1"
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "help"
```

This section is for the agent's internal execution path. Prefer natural-language skill invocation at the conversation layer.

## Failure Handling

- If sandbox, network, or missing-dependency issues block extraction or upload, fix the current skill path first and rerun it.
- Prefer local, bounded fixes such as enabling network, installing `rclone`, or correcting the extraction logic.
- Do not fan out into broad sub-agent exploration for routine skill failures.
- The default response to operational failure is: repair the skill path, rerun, then return the figure.

## Output Format

```json
{
  "arxiv_id": "2604.20834",
  "paper_title": "JoyAI-RA: Coordinated Embodied Learning for Mobile Manipulation",
  "paper_dir": "2604.20834-joyai-ra-coordinated-embodied-learning-for-mobile-manipulation",
  "source": "html",
  "requested_intent": "architecture",
  "candidate_total_figures": 11,
  "total_figures": 1,
  "figures": [
    {
      "figure_number": 1,
      "caption": "Figure 1: ...",
      "image_url": "https://arxiv.org/html/2604.20834v1/x1.png",
      "image_path": null,
      "match_score": 29,
      "matched_intent": "architecture",
      "paper_dir": "2604.20834-joyai-ra-coordinated-embodied-learning-for-mobile-manipulation",
      "source": "html"
    }
  ]
}
```

- Level 1: `image_url` is the original arXiv HTML asset URL.
- Level 2 and 3 with Cloudflare configured: matched local figures get uploaded and `image_url` points at your custom domain.
- Level 2 and 3 without Cloudflare configured: `image_url` stays null and `image_path` stays local.
- `source` is one of `html`, `arxiv_source`, `pdf`, or `none`.

## Key Files

| File | Purpose |
|------|---------|
| `arxiv_fig.py` | Core script with extraction, intent scoring, optional upload, and suggestion logging |
| `intent_keywords.yaml` | Maintained keyword dictionary for rule-based matching |
| `keyword_suggestions.jsonl` | Runtime suggestion log for improving the dictionary over time |
| `tests/test_arxiv_fig.py` | Repo-local tests for parsing and CLI help |
| `SKILL.md` | Usage and agent responsibilities |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Uploading every extracted figure | Only upload the matched local figures |
| Using ar5iv as fallback | Do not use it |
| Expecting every Level 2 figure to have a caption | Use file names when captions are empty |
| Treating upload failure as fatal | Keep `image_path` and return `upload_error` |
| Asking the user to provide command flags | Infer intent from the natural-language request and run the script internally |
| Expanding into broad agent exploration when the skill hits sandbox/network trouble | Repair the skill path and rerun instead |
