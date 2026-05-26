---
name: rss-dedupe
description: Use when normalized or fetched RSS items need same-content deduplication before semantic filtering, especially across mirrored WeChat/X feeds and repeated source entries.
---

# rss-dedupe

Deterministic same-content dedupe for RSS items.

## Role

`rss-dedupe` assigns stable `canonical_id` values and collapses obvious duplicate content records.

It does:

- normalize URLs for downstream matching
- derive stable content identifiers from WeChat, X/Twitter, arXiv, GitHub, and generic URLs
- group exact or near-exact duplicate feed entries into one canonical item
- preserve duplicate traceability under `duplicate_items`

It does not:

- decide whether two different writeups describe the same event
- decide digest inclusion
- write Chinese summaries

## Agent Tool Surface

```bash
python3 skill/rss-dedupe/rss_dedupe.py help
python3 skill/rss-dedupe/rss_dedupe.py dedupe --input rss-daily-output/2026-05-12/fetch/fetched_items.json --output rss-daily-output/2026-05-12/dedupe/deduped_items.json
```

## Downstream

The next skill is `rss-cluster`.
