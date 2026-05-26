---
name: rss-verify
description: Use when published RSS daily artifacts need a final verification record before the pipeline is considered complete.
---

# rss-verify

Verify required publish artifacts for RSS daily runs.

Current verification requires:

- `latest.json`
- `manifest.json`
- `daily/<date>.json`
- at least one `sources/*.json` file

It also performs lightweight digest content validation.

## Content Checks

`rss-verify` should catch obvious contract failures such as:

- missing top-level digest fields
- digest date mismatch
- missing or duplicate top-level `story_id`
- missing `title` or `summary` on story cards
- malformed `sections`
- mismatch between `stories` count and section item count
- mismatch between section `count` and actual item list size
- mismatch between top-level `counts` and per-section totals

It does not attempt deep semantic quality review.

## Agent Tool Surface

```bash
python3 skill/rss-verify/rss_verify.py help
python3 skill/rss-verify/rss_verify.py verify --publish-dir rss-daily-output/2026-05-12/publish-out --date 2026-05-12 --output rss-daily-output/2026-05-12/verify.json
```
