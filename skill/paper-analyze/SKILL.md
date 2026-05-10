---
name: paper-analyze
description: Use when the user wants one paper deeply analyzed into a final Markdown note, with stable sections, optional figure references, and direct output into an llm-wiki source directory configured in YAML.
---

# paper-analyze

Analyze one paper into a final wiki-ready Markdown note.

The important rule is:

- the **agent** does the real reading, synthesis, and judgment
- helper scripts only do deterministic support work such as source resolution, metadata extraction, figure extraction, and file writing

## Requirements Snapshot

- Handle one paper at a time.
- Accept arXiv URL, paper landing page URL, local PDF path, or pasted paper text.
- Produce a full Markdown note, not a short summary blob.
- Write the note directly into the configured `llm-wiki` source directory by default.
- Support draft output to a temporary directory when the user wants to preview first.
- Keep website publish logic out of this skill.

## Role Split

- `paper-analyze`
  - orchestrate deep paper analysis
  - have the agent read and summarize the paper
  - produce the final Markdown note
  - write that note into the wiki source directory
- `md-preview`
  - render one Markdown file into temporary HTML
  - start a local preview service
- `wiki-sync-page`
  - sync public wiki content into the website
- `paper_analyze.py`
  - helper only
  - resolve source type
  - derive metadata hints
  - optionally call `arxiv-fig`
  - write the final Markdown file

## Config Contract

This skill expects a YAML config that declares the wiki root and default paper output directory.

Minimum expected fields:

```yaml
wiki:
  root: /absolute/path/to/llm-wiki
  sources_dir: wiki/sources

paper_analyze:
  output_mode: write
  draft_dir: /tmp/paper-analyze
  language: zh
  image_store: r2
  r2_base_url: https://<your-r2-domain>/wiki-assets
```

Derived default output path:

```text
{wiki.root}/{wiki.sources_dir}/{slug}.md
```

If the config is missing, ask the user for the target wiki root instead of guessing.

## Input Contract

Accepted inputs:

- one arXiv URL
- one paper landing page URL
- one local PDF path
- one pasted abstract plus enough body text to analyze
- one explicit title only if the invoking agent can resolve the paper safely

This skill is single-paper only. If the user gives multiple papers, ask which one to process first.

## Output Modes

### `write`

- default
- write the final Markdown note into `llm-wiki`

### `draft`

- write the final Markdown note into a temporary directory
- use this when the user says "先预览" or wants to inspect before committing to the wiki

## Final Markdown Contract

The output is the final note, not an intermediate schema.

The note should contain:

```markdown
---
title:
source_type: paper
source_url:
publish_date:
domain:
tags:
images:
related_topics:
status: analyzed
---

# Title

## Core Information
## Research Problem
## Method Overview
## Key Takeaways
## Experimental Signals
## Strengths
## Limitations
## Critical Notes
## Related Topics
## Figure Notes
```

## Workflow

### 1. Resolve the source

Normalize the input into one source object:

- URL
- local PDF
- pasted text

If the source is weak, say so explicitly.

### 2. Read enough paper content

Prefer:

1. local PDF or provided full text
2. canonical paper page plus abstract
3. pasted excerpts

Do not fabricate sections that were not available.

### 3. Let the agent perform the actual analysis

This step is the core of the skill.

The agent should:

- read the available paper content
- identify the research problem
- explain the core method
- extract the main findings
- judge strengths and limitations
- decide which related wiki topics are appropriate

This skill is intentionally closer to the `evil-read-arxiv` logic than to a lightweight short-summary tool:

- produce a real paper note
- not just a one-paragraph summary
- include structured sections
- include figures when they help

### 4. Extract stable paper-note structure

At minimum identify:

- the research problem
- the core method
- the main results
- the practical or conceptual significance
- the paper's limits
- likely topic connections in your wiki

### 5. Handle figures

If useful figures are available:

- upload them to R2 or record the intended R2 target
- store public image URLs in the Markdown frontmatter `images`
- reference them in `## Figure Notes`

Do not inline binary assets into the note.

When an arXiv paper has a useful overview, architecture, system, or pipeline figure, prefer calling the existing helper path instead of inventing image handling:

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "<arxiv_id>" --intent "architecture"
```

### 6. Generate the final Markdown note

This note should read like a reusable research note, not a blog post and not just a checklist.

Target qualities:

- structured
- concise but substantive
- future-query friendly
- suitable for later topic and synthesis linking

### 7. Write the file

In `write` mode:

- slugify the paper title or paper identifier
- write to the configured wiki source directory

In `draft` mode:

- write to the configured draft directory

Always report the final path written.

Use `paper_analyze.py` as the helper writer:

```bash
python3 /home/tenstep/workspace/followhub/skill/paper-analyze/paper_analyze.py write --config /path/to/config.yaml --input "<source>" --title "<final title>" --summary "<final summary>"
```

The agent should treat the script as a sink for already-decided content, not as the primary analyzer.

### 8. Suggest follow-up only

After writing, optionally suggest:

- one or two related topics to update
- whether this paper looks worth a future synthesis page

Do not sync the website from this skill.

## Writing Style

- optimize for future retrieval and comparison
- avoid hype and filler
- separate author claims from your synthesis
- when evidence is partial, say that clearly
- prefer tight technical prose over long narrative

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Returning only a short summary | Produce the full Markdown note with stable sections |
| Writing directly for the blog | Keep the note structured and source-oriented |
| Hard-coding one wiki path | Read the configured path from YAML |
| Mixing website sync into analysis | Leave that to `wiki-sync-page` |
| Treating figures as mandatory | Include figure notes only when they add value |
| Letting the helper script replace the agent's reasoning | Use the script only for deterministic support and writing |

## Notes From `evil-read-arxiv`

Useful parts reused:

- single-paper focus
- stable paper-note structure
- explicit problem / method / result / limitation breakdown
- figures treated as first-class supporting material
- the idea that one paper should become one durable note

Deliberately changed:

- no Obsidian-specific assumptions
- no arXiv-only assumption
- no giant all-in-one template with excessive boilerplate
- output is tailored for `llm-wiki`, R2-hosted images, and later website sync
- the agent, not the script, remains responsible for the actual paper understanding
