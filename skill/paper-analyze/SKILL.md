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
- Default to the strong `OpenVLA` note standard already present in this repo.
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
primary_domain_slug:
domain_slugs:
tags:
images:
related_topics:
status: analyzed
---

# Title

## 太长不看
## 直观理解
## 核心信息
## 背景与问题
## 论文摘要（英文原文）
## 论文摘要（中文翻译）
## 方法
## 结果
## 洞察
## 风险与判断

**局限：**
- ...

**适用场景：**
- ...

**最终判断：**
- ...

## 结果速览表
## 相关主题
```

Domain and label rules:

- `domain`, `primary_domain_slug`, and the first `domain_slugs` entry must name the material's main wiki domain.
- Keep `domain_slugs` to 1 entry by default; use 2 only when the material clearly spans two primary domains.
- Keep `tags` to 1 concise label by default, 2 at most.
- Keep `related_topics` focused; prefer 1 topic, 2 only when both are genuinely useful reading routes.

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
- prioritize succeeding in one pass when source quality is sufficient
- before writing, fill obvious metadata gaps first:
  - author names
  - author affiliations when the source page exposes them
  - arXiv-derived `hjfy` translation link
  - main architecture / result figures when available
  - strongest result table
- do not leave placeholder-quality fields such as vague author labels when the source page already exposes the data
- if the HTML page gives weak or incomplete abstract text, fall back to the arXiv abstract page
- if a section reads like generic domain commentary rather than paper-specific analysis, rewrite it before writing

### 3.5 Quality Floor: OpenVLA Standard

Treat the existing `OpenVLA: An Open-Source Vision-Language-Action Model` note in this repo as the default quality floor.

This is not a premium or optional standard. It is the baseline expected output.

That means:

- every required section must contain paper-specific substance
- `方法` must explain the actual mechanism, not only restate the problem
- `结果` must include concrete targets, numbers, or ablations when the source provides them
- `洞察` must contain real synthesis and judgment, not generic praise
- figures should be included when they materially improve comprehension
- the note must be strong enough to support future `topic` and `synthesis` pages without rereading the paper

If time or batch size pressures appear, do not lower note quality.
Instead, process fewer papers per round or parallelize with one paper per worker.

### 4. Extract stable paper-note structure

For fast reading, prefer one stable compact structure:

- `太长不看`
  - 2-4 句
  - only final judgment and value
- `直观理解`
  - one short paragraph
  - explain what the system is really doing in plain language
- `背景与问题`
  - why this problem matters
  - where prior methods fall short
- `摘要`
  - keep both original English abstract and Chinese translation
- `方法`
  - short overview first
  - then 3-5 method bullets
  - place architecture / pipeline figures here
  - match the richer OpenVLA-style structure when the source supports it
- `结果`
  - 3-5 high-signal results
  - include one compact result table
  - place result figures here
- `洞察`
  - what is actually worth remembering
  - relation to prior methods
  - what can be borrowed
- `风险与判断`
  - limits
  - where this applies
  - your final judgment

Section intent:

- `太长不看`
  - answer only: is this worth remembering and why
  - no method details here
- `直观理解`
  - explain the paper in plain language
  - if the paper is a system, describe the loop or pipeline
- `背景与问题`
  - include motivation
  - explain why this problem matters now
  - state what prior methods still fail to provide
  - internally structure it as:
    - `动机`
    - `问题缺口`
- `摘要`
  - keep the original English abstract
  - add a faithful Chinese translation
  - do not paraphrase away key numbers or constraints
- `方法`
  - first: one short overview paragraph
  - then: 3-5 bullets for mechanism / pipeline / components
  - if useful, say why the method could work, not just what it contains
  - internally structure it as:
    - `方法概述`
    - `核心机制`
    - `方法拆解`
- `结果`
  - list only the most decision-relevant outcomes
  - keep 1 compact table
  - avoid dumping every benchmark number
  - but do include concrete comparison targets or key numbers when available
- `洞察`
  - what is actually worth retaining after reading
  - relation to prior approaches
  - what can be borrowed into future work
  - internally structure it as:
    - `核心 insight`
    - `和已有方法的关系`
    - `可借鉴点`
- `风险与判断`
  - limits, fragile assumptions, and deployment caveats
  - where this paper should and should not be used
  - whether this paper is worth follow-up
  - must use exact labeled blocks so downstream package fields are not empty:
    - `**局限：**`
    - `**适用场景：**`
    - `**最终判断：**`
  - each labeled block must contain at least one paper-specific bullet or sentence
- `相关主题`
  - knowledge-base navigation only
  - keep this short and late in the page

Do not expand into too many sections. This skill is for dense, fast reading, not for exhaustive lab notebooks.

Inside each section, prefer micro-structure over long prose:

- use 2-4 short bullets when possible
- each bullet should carry one idea only
- avoid mixing motivation, mechanism, and judgment in a single sentence block
- reject vague lines such as:
  - broad industry commentary without tying back to the paper
  - generic claims like “this is important for the field” without a concrete reason
  - benchmark summaries that omit the actual comparison target

### 5. Handle figures

If useful figures are available:

- if the figure already has a stable online URL, use it directly
- if the figure was extracted locally from source or PDF, upload it to R2 or record the intended R2 target
- store public image URLs in the Markdown frontmatter `images`
- place them in the most relevant section:
  - pipeline / architecture figures -> `方法`
  - benchmark / performance figures -> `结果`
  - representation / qualitative insight figures -> `洞察`

When the input source is a PDF, figure extraction is still required on a best-effort basis.
Do not treat PDF inputs as text-only by default.
At minimum, try to surface:

- one overview or architecture figure when available
- one key result figure when available

For PDF-derived figures, do not attach images purely by extraction order.
You must align each chosen figure with nearby page text or caption text first.
Prefer this order of evidence:

1. explicit `Fig. N:` caption on the same page
2. nearby section title such as `Architecture`, `Prompt`, `Results`, `Cross-embodiment`
3. page-level semantic match between the figure and the section where it will be placed

If you cannot determine the figure meaning, leave it out rather than attaching a semantically wrong image.

For PDF figure generation, prefer this extraction order:

1. exact figure crop when the figure region can be isolated with reasonable confidence
2. page crop around the caption-linked figure block
3. embedded image extraction as fallback only

Use embedded image extraction only when better layout-aware PDF paths are unavailable.
Do not let embedded-image convenience override semantic correctness.

If extraction fails because the PDF is image-hostile or the local environment lacks the needed dependency,
say that explicitly in the result instead of silently omitting figure handling.

Do not inline binary assets into the note.

When an arXiv paper has a useful overview, architecture, system, or pipeline figure, prefer calling the existing helper path instead of inventing image handling:

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-fig/arxiv_fig.py "<arxiv_id>" --intent "architecture"
```

When the source is a local PDF or a non-arXiv PDF URL, use the local PDF figure path in `paper_analyze.py`
instead of relying on `arxiv-fig`.

### 6. Generate the final Markdown note

This note should read like a paper digest card:

- structured
- compact
- skimmable in under 2 minutes
- strong enough for later topic and synthesis linking

When deciding what to cut, keep:

- judgment
- method skeleton
- strongest results
- memorable insight

Cut first:

- long prose
- repeated framing
- weak background filler
- exhaustive related work narration


### 6.5 Pre-write completeness check

Before writing the final note, do a self-check against the page-facing fields that the wiki package expects.

The note is not ready if any of these are empty or placeholder-like:

- frontmatter source type, source URL, date, domain, tags, related topics, and status
- all required paper sections
- `风险与判断` labeled blocks:
  - `**局限：**`
  - `**适用场景：**`
  - `**最终判断：**`
- arXiv links when available:
  - abs/html link
  - PDF link
  - hjfy translation link
- at least one useful figure when the source exposes a meaningful figure URL

If a field is missing, fill it from the paper analysis before calling the helper writer. Do not rely on later website sync to infer missing interpretation.

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
- when `paper_analyze.language` is `zh`, keep only `论文摘要（英文原文）` in English
- all other analysis sections should be written in Chinese

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Returning only a short summary | Produce the full Markdown note with stable sections |
| Writing directly for the blog | Keep the note structured and source-oriented |
| Hard-coding one wiki path | Read the configured path from YAML |
| Mixing website sync into analysis | Leave that to `wiki-sync-page` |
| Treating figures as mandatory | Include figure notes only when they add value |
| Letting the helper script replace the agent's reasoning | Use the script only for deterministic support and writing |
| Producing thin “summary cards” under batch pressure | Batch size is not a valid reason to drop below the OpenVLA quality floor |

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
