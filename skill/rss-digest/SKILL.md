---
name: rss-digest
description: Use when filtered and enriched RSS items need to be grouped into a daily digest JSON bundle for FollowHub.
---

# rss-digest

Build the daily RSS digest bundle.

## Responsibilities

- group selected items into story-oriented digest cards
- generate daily highlights
- preserve source and domain metadata for publish

Reads:

- `rss-daily-output/<date>/enrich_results.json`

Writes:

- `rss-daily-output/<date>/daily-digest.json`

## Output Shape

`rss-digest` emits story-level items rather than raw-entry-level rows.

Each selected story should preserve:

- `story_id`
- `story_status`
- representative item fields
- `mention_count`
- `related_items`

Canonical top-level digest fields:

- `summary`
- `highlights`
- `counts`
- `stories`

Compatibility fields allowed during transition:

- `sections`

## Non-Goals

`rss-digest` does not:

- decide same-content dedupe
- recompute `canonical_id`
- recompute `story_id`
- decide semantic inclusion on its own
- publish page data directly

## Agent Tool Surface

```bash
python3 skill/rss-digest/rss_digest.py help
python3 skill/rss-digest/rss_digest.py build --input rss-daily-output/2026-05-12/enrich_results.json --output rss-daily-output/2026-05-12/daily-digest.json
```
