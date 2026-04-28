# arxiv-view Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `arxiv-view` as a static-directory viewer that consumes `arxiv-find` outputs and provides a unified HTML experience for `daily`, `backfill`, and `search`, including client-side filtering and browser-local favorites with clipboard export of selected arXiv IDs.

**Architecture:** `arxiv-view` is a read-only presentation skill. It does not re-run retrieval, ranking, or profile resolution. It takes one or more `arxiv-find` output files, normalizes them into a single view model, writes a static bundle (`index.html`, `app.js`, `styles.css`, `data.json`), and leaves persistence to the browser via `localStorage`.

**Tech Stack:** Python 3, JSON, static HTML/CSS/vanilla JavaScript, browser `localStorage`, Clipboard API.

---

## Route Summary

This plan follows the approved staged route:

1. `arxiv-view`
   - phase 1 target in this document
   - static rendering only
2. `arxiv-enrich`
   - future enrichment and ranking layer
   - also the default internal phase behind `arxiv-find` outputs
3. `arxiv-workflow`
   - future orchestration skill that chains `find -> enrich -> view -> publish`

`arxiv-view` phase 1 only consumes `arxiv-find` outputs.

## Scope

### In Scope

- Static-directory output:
  - `index.html`
  - `app.js`
  - `styles.css`
  - `data.json`
- Input modes:
  - one `daily` result
  - one `search` result
  - one `backfill` overview plus linked daily result files
- Unified card/list rendering across all three modes
- Client-side filtering and keyword search
- Favorites stored in browser `localStorage`
- One-click clipboard export of favorite arXiv IDs

### Out of Scope

- Re-running `arxiv-find`
- Server-side API
- Multi-user state
- Syncing favorites across devices
- Computing enrichment fields from scratch inside `arxiv-view`
- Publishing to R2 or GitHub Pages

## Existing Inputs and Patterns

### Existing producer

- `skill/arxiv-find/arxiv_find.py`
  - emits `daily` JSON
  - emits `search` JSON
  - emits `backfill` overview plus daily artifacts

### Existing viewer references

- `ref/Arxiv-tracker/arxiv_tracker/sitegen.py`
  - static HTML generation
  - digest-oriented card layout
- `ref/hermes-arxiv-agent/viewer/`
  - static directory shape
  - client-side filtering
  - `localStorage` favorites
- `ref/ArxivReader/src/arxiv_reader/web_server.py`
  - information architecture ideas for richer navigation

### Important constraints

- Keep `arxiv-view` separate from `arxiv-find`
- Keep inputs file-based and explicit
- Prefer agent-friendly static outputs over live server complexity

## Planned Files

### New files

- `skill/arxiv-view/SKILL.md`
  - skill contract, requirements snapshot, command surface
- `skill/arxiv-view/arxiv_view.py`
  - input loading, normalization, bundle writing
- `skill/arxiv-view/view_template/index.html`
  - static shell
- `skill/arxiv-view/view_template/app.js`
  - client filtering, favorites, clipboard export
- `skill/arxiv-view/view_template/styles.css`
  - static styling
- `skill/arxiv-view/tests/test_arxiv_view.py`
  - Python-side unit coverage
- `skill/arxiv-view/tests/fixtures/`
  - representative `daily`, `search`, and `backfill` JSON inputs

### Files intentionally unchanged

- `skill/arxiv-find/arxiv_find.py`
  - phase 1 assumes current output shape
- `README.md`
  - can be updated after implementation if needed, but not required for the first pass

## Data Model

`arxiv-view` should normalize all input modes into a single internal shape.

By contract, `arxiv-find` should eventually expose these fields by default, even if some are temporarily empty in early iterations:

```json
{
  "mode": "daily|search|backfill",
  "title": "string",
  "subtitle": "string",
  "items": [
    {
      "arxiv_id": "2604.21924",
      "title": "Long-Horizon Manipulation via Trace-Conditioned VLA Planning",
      "one_liner_zh": "一句话总结",
      "summary_cn": "中文总结",
      "abstract_en": "English abstract",
      "authors": ["..."],
      "first_affiliation": "University X",
      "affiliations": ["University X", "Institute Y"],
      "categories": ["cs.RO"],
      "published": "2026-04-23T17:59:04Z",
      "updated": "2026-04-23T17:59:04Z",
      "pdf_url": "https://arxiv.org/pdf/...",
      "html_url": "https://arxiv.org/abs/...",
      "code_urls": ["https://github.com/..."],
      "project_urls": ["https://project.page/..."],
      "citation_count": 12,
      "influential_citation_count": 3,
      "hot_score": 1.8,
      "relevance_score": 3.55,
      "quality_score": 2.1,
      "overall_score": 4.3,
      "matched_keywords": ["VLA"],
      "favorite_default": false,
      "source_day": "2026-04-24",
      "source_mode": "daily"
    }
  ],
  "meta": {
    "days": [],
    "counts": {},
    "generated_at": "..."
  }
}
```

`backfill` should flatten daily items into one display set while preserving `source_day`.

Phase 1 requirement for `arxiv-view`:

- if `one_liner_zh`, `summary_cn`, `first_affiliation`, or hotness fields are missing, the viewer must degrade gracefully
- `abstract_en` should be treated as the stable fallback field name even if current `arxiv-find` still emits `summary`

## UX Contract

### Default entry behavior

- `daily`
  - show one-day digest view
- `search`
  - show one result list view
- `backfill`
  - default to a grouped timeline by day

### Client interactions

- keyword search over:
  - title
  - authors
  - categories
  - one-line summary
  - Chinese summary
  - English abstract
  - matched keywords
- card information hierarchy:
  - title, arXiv ID, favorite toggle
  - date / category / authors / first affiliation
  - hotness or score badges when present
  - one-line summary visible by default
  - Chinese summary visible by default
  - English abstract collapsed by default
- filters:
  - mode-independent free text
  - category filter
  - source day filter when available
  - favorites-only toggle
- favorite action:
  - toggle star/bookmark per card
  - persist to `localStorage`
- export action:
  - collect favorite `arxiv_id`s
  - copy newline-separated IDs to clipboard

### Empty states

- no items loaded
- filter returns zero cards
- favorites export attempted with zero favorites

## Testing Strategy

### Python-side tests

- input loader accepts `daily`
- input loader accepts `search`
- input loader accepts `backfill` overview and linked daily files
- normalizer preserves `source_day`
- bundle writer creates all four output files
- invalid input fails clearly
- missing enrich fields degrade gracefully instead of crashing

### Browser-side behavior coverage

Since phase 1 is repo-local and static:

- keep browser logic simple enough to validate via deterministic `data.json`
- include a smoke HTML fixture test by asserting generated HTML references `app.js`, `styles.css`, and `data.json`
- deeper browser automation can wait for later if needed

## Implementation Tasks

### Task 1: Scaffold `arxiv-view` skill and fixtures

**Files:**
- Create: `skill/arxiv-view/SKILL.md`
- Create: `skill/arxiv-view/arxiv_view.py`
- Create: `skill/arxiv-view/tests/test_arxiv_view.py`
- Create: `skill/arxiv-view/tests/fixtures/daily.json`
- Create: `skill/arxiv-view/tests/fixtures/search.json`
- Create: `skill/arxiv-view/tests/fixtures/backfill_overview.json`
- Create: `skill/arxiv-view/tests/fixtures/backfill_day_2026-04-24.json`
- Create: `skill/arxiv-view/tests/fixtures/backfill_day_2026-04-25.json`

- [ ] Write failing tests for fixture loading and mode detection.
- [ ] Run the `arxiv-view` tests and confirm they fail because files and functions do not exist.
- [ ] Add the minimal Python module with mode parsing stubs.
- [ ] Re-run the targeted tests and confirm the loader tests pass.
- [ ] Commit the scaffolding.

### Task 2: Build normalized view model

**Files:**
- Modify: `skill/arxiv-view/arxiv_view.py`
- Modify: `skill/arxiv-view/tests/test_arxiv_view.py`

- [ ] Write failing tests for normalization of `daily`, `search`, and `backfill`.
- [ ] Verify the failing expectations include flattened `backfill` items with preserved `source_day`.
- [ ] Implement normalization functions:
  - `load_input()`
  - `normalize_daily()`
  - `normalize_search()`
  - `normalize_backfill()`
- [ ] Re-run the tests and confirm all normalization tests pass.
- [ ] Commit the normalized model layer.

### Task 3: Add static bundle writer

**Files:**
- Modify: `skill/arxiv-view/arxiv_view.py`
- Create: `skill/arxiv-view/view_template/index.html`
- Create: `skill/arxiv-view/view_template/app.js`
- Create: `skill/arxiv-view/view_template/styles.css`
- Modify: `skill/arxiv-view/tests/test_arxiv_view.py`

- [ ] Write failing tests for bundle creation and file presence.
- [ ] Verify the failure indicates missing template files or writer functions.
- [ ] Implement bundle output that writes:
  - `index.html`
  - `app.js`
  - `styles.css`
  - `data.json`
- [ ] Keep the template references stable and relative.
- [ ] Re-run the tests and confirm bundle output tests pass.
- [ ] Commit the static bundle layer.

### Task 4: Add client-side filtering and favorites

**Files:**
- Modify: `skill/arxiv-view/view_template/index.html`
- Modify: `skill/arxiv-view/view_template/app.js`
- Modify: `skill/arxiv-view/view_template/styles.css`
- Modify: `skill/arxiv-view/SKILL.md`

- [ ] Add UI controls for:
  - free-text search
  - favorites-only toggle
  - source-day filter when present
  - category filter when present
- [ ] Add browser-local favorites using `localStorage`.
- [ ] Add clipboard export of favorite arXiv IDs.
- [ ] Add visible empty states for no results and no favorites.
- [ ] Manually review the generated HTML/CSS/JS for a coherent static flow.
- [ ] Commit the interactive client layer.

### Task 5: Polish the skill contract and usage docs

**Files:**
- Modify: `skill/arxiv-view/SKILL.md`

- [ ] Document the exact input contract: it consumes `arxiv-find` outputs only.
- [ ] Document the generated static-directory shape.
- [ ] Document the favorites and clipboard workflow.
- [ ] Document that `arxiv-view` is render-only and does not retrieve papers.
- [ ] Commit the finalized skill documentation.

## Risks and Mitigations

- **Risk:** `arxiv-find` output shape changes later.
  - Mitigation: keep normalization isolated in one Python module.
- **Risk:** current `arxiv-find` output is still thinner than the long-term contract.
  - Mitigation: phase 1 viewer accepts the future contract but gracefully maps current fields such as `summary` into `abstract_en`.
- **Risk:** backfill overview paths may be absolute and machine-specific.
  - Mitigation: normalize file loading via explicit CLI arguments or relative resolution from the overview file.
- **Risk:** browser-only favorites are local to one browser.
  - Mitigation: phase 1 explicitly treats clipboard export as the workflow handoff.
- **Risk:** one template may feel too generic across modes.
  - Mitigation: preserve `mode` and `source_day` in the view model so mode-specific sections can be layered later without rewriting the model.

## Deliverable Definition

Phase 1 is complete when:

- `arxiv-view` exists as a repo-local skill
- it renders `daily`, `search`, and `backfill` outputs from `arxiv-find`
- the output is a static directory bundle
- users can favorite papers in the browser and copy favorite arXiv IDs to the clipboard
- repo-local tests for the Python normalization and bundle writer pass
