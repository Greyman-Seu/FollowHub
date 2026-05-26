# RSS Daily TODO

This note tracks the RSS daily pipeline for personal WeChat / X/Twitter subscriptions.

The goal is not to replace `arxiv-daily`. The goal is to provide a parallel daily push workflow with the same operational shape:

- subscribe to sources
- collect new items every day
- remove obvious duplicates
- group same-story coverage
- review what is worth reading
- produce a clean daily digest for publishing

## Scope

The RSS work stays inside the `rss-*` skill chain:

1. `rss-collect`
2. `rss-normalize`
3. `rss-fetch`
4. `rss-dedupe`
5. `rss-cluster`
6. `rss-prefilter`
7. `rss-filter`
8. `rss-enrich`
9. `rss-digest`
10. `rss-publish`
11. `rss-verify`

Out of scope:

- full wiki integration
- long-term entity graph design
- replacing `follow-publish`
- trying to solve every semantic merge with LLM logic first

## What Exists Today

Already implemented in code:

- pipeline orchestrator
- source collection
- normalization
- content fetch
- deterministic same-content dedupe
- lightweight story clustering
- prefilter / filter handoff
- enrich stage
- digest build
- publish packaging
- basic artifact verification

Already covered by tests:

- end-to-end local feed run
- missing prefilter stop condition
- same WeChat article deduped into one story
- auto-worker filtering for focus keywords and ad-like entries
- date-only filtering
- previous-day story suppression during auto filter

## Personal TODO

For personal use, the remaining work should stay small and practical. The goal is to reduce daily review friction, not to keep expanding infrastructure.

Highest-value remaining items:

- make `rss-prefilter` / `rss-filter` review instructions explicit and reusable
- provide a personal RSS config example with recommended defaults
- keep fixture coverage growing only for cases that affect daily reading quality
- avoid adding heavyweight architecture unless it clearly improves your everyday push results

State already added since this note started:

- explicit artifact contract
- story-first digest output with compatibility fields
- recent story history artifact
- persistent story ledger under `rss-daily-output/_state/story-ledger.json`
- `new` / `followup` / `repeat` story semantics in `rss-cluster`
- auto-filter now distinguishes recent `followup` from recent `repeat`
- prefilter/filter inputs now receive recent story history context

## Execution Order

### 1. Freeze reusable reviewer templates

Status: in progress

Keep one reusable review contract for:

- title/source-only prefilter
- final semantic filter

These templates should make the daily judgment standard stable even when sources change.

### 2. Ship a personal RSS config example

Status: pending

Provide a compact example with recommended defaults for:

- `history_lookback_days`
- `lookback_days`
- `max_items_per_source`
- `keywords`
- `exclude_keywords`
- source grouping by WeChat / X / generic RSS

### 3. Keep acceptance fixtures focused

Status: in progress

Fixture expansion should stay tied to real personal-use pain points:

- mirror duplicates
- followup vs repeat
- recent history hints
- source overlap cases that change whether you want to read the item

### 4. Keep verify lightweight

Status: in progress

`rss-verify` should catch packaging and obvious contract mistakes, but should not become a deep content critic.

## Decision Notes

Why this pipeline keeps `prefilter` and `filter`:

- RSS sources are noisier than arXiv
- subscription feeds contain ads, reposts, commentary, and low-signal chatter
- daily push quality depends on human or agent review, not just keyword match

Why this pipeline keeps both `rss-dedupe` and `rss-cluster`:

- same-content duplicate and same-story duplicate are different problems
- publish should not be the layer that guesses semantic merges

Why `dedupe -> cluster -> enrich` remains the right order:

- avoid enriching obvious duplicates
- let digest operate on story-grouped records
- keep Chinese text generation focused on reviewed candidates
