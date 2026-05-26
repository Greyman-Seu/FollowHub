---
name: rss-publish
description: Use when RSS daily digests need to be packaged into page-ready Follow data artifacts and synced into the page submodule.
---

# rss-publish

Package RSS digests into publishable Follow data.

## Role

`rss-publish` should reuse the canonical `follow-publish` artifact builder rather than maintain a parallel page JSON format.

Reads:

- `rss-daily-output/<date>/daily-digest.json`

Writes:

- `rss-daily-output/<date>/publish-out/...`

## Hard Boundaries

`rss-publish` only packages approved digest data.

It may:

- add `date`
- build `latest.json`
- build daily publish artifacts
- sync source bundles required by the page layer

It must not:

- recompute `canonical_id`
- recompute `story_id`
- recompute `story_status`
- decide semantic dedupe
- decide digest inclusion

If grouping is wrong, the fix belongs upstream in `rss-dedupe`, `rss-cluster`, `rss-prefilter`, or `rss-filter`.

## Agent Tool Surface

```bash
python3 skill/rss-publish/rss_publish.py help
python3 skill/rss-publish/rss_publish.py build-daily --input rss-daily-output/2026-05-12/daily-digest.json --output-dir rss-daily-output/2026-05-12/publish-out
```
