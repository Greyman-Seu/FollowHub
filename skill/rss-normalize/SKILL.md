---
name: rss-normalize
description: Use when raw RSS entries need to be converted into the shared FollowHub source content contract before filtering or enrichment.
---

# rss-normalize

Normalize raw RSS entries into a shared contract.

## Responsibilities

- map WeChat / X / generic RSS fields into one stable schema
- preserve source metadata under `raw_meta`
- guarantee required fields exist even when values are empty

Reads:

- `rss-collect-output/<date>-raw.json`

Writes:

- `rss-daily-output/<date>/normalize/normalized_items.json`

It does not:

- deduplicate same-content entries across sources
- assign `canonical_id`
- assign `story_id`
- assign `story_status`
- merge same-story coverage semantically

## Contract Notes

- this stage is deterministic
- downstream stages may rely on stable field presence
- `normalized_url` may be populated here, but semantic identity still starts later in `rss-dedupe`

## Agent Tool Surface

```bash
python3 skill/rss-normalize/rss_normalize.py help
python3 skill/rss-normalize/rss_normalize.py normalize --input rss-collect-output/raw.json --output rss-daily-output/2026-05-12/normalize/normalized_items.json
```
