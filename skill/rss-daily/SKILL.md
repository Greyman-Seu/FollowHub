---
name: rss-daily
description: Use when the user asks for a daily digest from RSS-backed WeChat, X/Twitter, or other subscribed feeds; this skill must execute the explicit collect -> normalize -> fetch -> dedupe -> cluster -> prefilter -> filter -> enrich -> digest -> publish -> verify chain.
---

# rss-daily

Pipeline-level skill for RSS daily follow-up.

## Required Entry Point

```bash
python3 skill/rss-daily/run_daily.py daily --config followhub.yaml
```

## Execution Contract

For a normal daily run, the agent must execute these stages in order:

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

## Artifact-Driven Boundary

The orchestrator may call tool-type skills directly.

Normal production use should keep `rss-prefilter` and `rss-filter` as agent-reviewed worker stages.

For local testing, `rss-daily` also supports:

```bash
python3 skill/rss-daily/run_daily.py daily --config followhub.yaml --auto-workers
```

`--auto-workers` is a testing-only fallback that auto-generates prefilter and filter outputs so one RSS source can be exercised end-to-end without manual worker artifacts.

Rules that are hard to encode should stay agent-driven:

- ambiguous story merges
- borderline include/exclude decisions
- Chinese one-line summaries
- Chinese summaries
