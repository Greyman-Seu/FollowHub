---
name: rss-fetch
description: Use when normalized RSS entries need URL-based content fetching before semantic filtering, especially for WeChat articles and X/Twitter thread pages.
---

# rss-fetch

Fetch full content for RSS items when feed summaries are not enough.

## Responsibilities

- fetch or preserve article body text for RSS items
- keep URL-derived content separate from raw feed metadata
- emit one fetched bundle for downstream filtering and enrichment

## Agent Tool Surface

```bash
python3 skill/rss-fetch/rss_fetch.py help
python3 skill/rss-fetch/rss_fetch.py fetch --input rss-daily-output/2026-05-12/normalize/normalized_items.json --output rss-daily-output/2026-05-12/fetch/fetched_items.json
```
