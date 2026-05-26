---
name: rss-cluster
description: Use when deduped RSS items need lightweight story grouping across same-day and cross-day repeated coverage, while preserving agent handoff for ambiguous event merges.
---

# rss-cluster

Lightweight story grouping for RSS items.

## Role

`rss-cluster` groups deduped items into story-level clusters and marks whether each item is new, a followup, or a repeat.

It does:

- assign `story_id`
- assign `story_status`
- preserve story grouping hints and ambiguity markers
- emit agent handoff tasks for ambiguous clustering cases

It does not:

- decide digest inclusion
- generate Chinese summaries
- replace a full wiki/entity system

## Agent Tool Surface

```bash
python3 skill/rss-cluster/rss_cluster.py help
python3 skill/rss-cluster/rss_cluster.py cluster --input rss-daily-output/2026-05-12/dedupe/deduped_items.json --output rss-daily-output/2026-05-12/cluster/clustered_items.json
```

## Status Semantics

`story_status` is assigned at the story-group level, not as an isolated per-row guess.

- `new`: the primary item for a story group
- `repeat`: same-content mirrors or duplicate-heavy representatives
- `followup`: a later item in the same story group with a different `canonical_id`

The story index may still surface `new` when the representative item is the primary record, even if some related items inside the same story are marked `repeat` or `followup`.

## Downstream

The next skill is `rss-prefilter` or `rss-filter`, depending on the caller workflow.
