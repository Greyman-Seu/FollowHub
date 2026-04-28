# arxiv Data Contract and Skill Roadmap

**Goal:** Lock the long-term contract between `arxiv-find`, `arxiv-enrich`, `arxiv-view`, and the future `arxiv-workflow` so implementation can proceed without re-debating field ownership.

**Status:** Approved planning decision

---

## Core Decision

`arxiv-find` remains the user-facing entry skill, but its **default output contract** is a richer, post-enrichment shape.

This means:

- users invoke `arxiv-find`
- `arxiv-find` is allowed to call or embed `arxiv-enrich` internally by default
- `arxiv-enrich` still exists as a standalone skill for re-running, patching, or upgrading fields later

In short:

```text
arxiv-find = retrieve + normalize + enrich-by-default
```

This avoids pushing users into a two-step `find -> rank` manual workflow while still preserving modularity.

## Agent Execution Rule

The primary intended interface is **agent skill usage**, not human-first CLI usage.

Execution rule:

- single arXiv ID
  - the main agent may enrich inline
- multiple arXiv IDs
  - the main agent should prefer subagent orchestration
  - `arxiv-find` acts as the orchestrator
  - `arxiv-enrich` acts as the default worker

This keeps high-level control, deduplication, and presentation assembly in the main thread while parallelizing the independent enrich work.

## Skill Roles

### `arxiv-find`

Responsibilities:

- retrieval
- pagination
- daily new-submission semantics
- per-day backfill slicing
- shared profile loading
- base normalization
- default enriched output contract
- multi-ID orchestration for downstream enrich work

Should not own:

- HTML rendering
- long-term browser state
- publication hosting

### `arxiv-enrich`

Responsibilities:

- relevance scoring
- hotness fields
- quality or overall score
- author-affiliation enrichment
- one-line Chinese summary
- Chinese summary
- code/project links when they require extra extraction work

Should exist both as:

- an internal phase of `arxiv-find`
- a standalone skill callable later on existing result files
- the default subagent worker when many arXiv IDs need independent enrichment

### `arxiv-view`

Responsibilities:

- render-only static viewer
- browser-local favorites
- clipboard export of selected arXiv IDs
- graceful display of whatever enriched fields are present

Should not own:

- retrieval
- ranking
- translation
- metadata crawling

### `arxiv-workflow`

Future orchestration wrapper for:

```text
find -> enrich -> view -> publish
```

## Output Contract

`arxiv-find` should converge on this item shape:

```json
{
  "arxiv_id": "2604.21924",
  "title": "Long-Horizon Manipulation via Trace-Conditioned VLA Planning",
  "authors": ["Isabella Liu", "Sifei Liu"],
  "first_affiliation": "University X",
  "affiliations": ["University X", "Institute Y"],

  "published": "2026-04-23T17:59:04Z",
  "updated": "2026-04-23T17:59:04Z",
  "source_day": "2026-04-24",
  "categories": ["cs.RO"],

  "one_liner_zh": "一句话总结",
  "summary_cn": "中文总结",
  "abstract_en": "English abstract",

  "citation_count": 12,
  "influential_citation_count": 3,
  "hot_score": 1.8,
  "relevance_score": 3.55,
  "quality_score": 2.1,
  "overall_score": 4.3,

  "matched_keywords": ["VLA"],

  "pdf_url": "https://arxiv.org/pdf/...",
  "html_url": "https://arxiv.org/abs/...",
  "code_urls": ["https://github.com/..."],
  "project_urls": ["https://project.page/..."]
}
```

## Field Guarantees

### Required in all normal outputs

- `arxiv_id`
- `title`
- `authors`
- `published`
- `updated`
- `categories`
- `abstract_en`
- `pdf_url`
- `html_url`
- `matched_keywords`

### Required fields that may be empty in early iterations

- `first_affiliation`
- `affiliations`
- `one_liner_zh`
- `summary_cn`
- `citation_count`
- `influential_citation_count`
- `hot_score`
- `relevance_score`
- `quality_score`
- `overall_score`
- `code_urls`
- `project_urls`

The field should exist even if the current value is empty, `0`, `[]`, or `null` according to its type convention.

## UI Contract for `arxiv-view`

Default visible card order:

1. title + arXiv ID + favorite toggle
2. score / heat badges when present
3. date + category + authors + first affiliation
4. one-line Chinese summary
5. Chinese summary
6. English abstract in a collapsed section
7. links: Abs / PDF / Code / Project

Degrade gracefully:

- if `summary_cn` is empty, show `暂无中文总结`
- if `one_liner_zh` is empty, do not invent one inside the viewer in the long-term contract
- if `first_affiliation` is empty, render `—`
- if hotness fields are empty, omit the badge block

## Phase Order

1. `arxiv-view`
   - phase 1 already underway
   - must support future enriched fields but tolerate current thin output
2. `arxiv-enrich`
   - next major implementation target
   - should backfill the contract above
3. `arxiv-workflow`
   - only after `find`, `enrich`, and `view` stabilize

## Immediate Follow-through

The current `arxiv-view` plan should be read with this contract in mind:

- implement tolerant field mapping now
- do not hard-code assumptions that summaries or affiliation are always populated
- prepare card layout for future richer fields
