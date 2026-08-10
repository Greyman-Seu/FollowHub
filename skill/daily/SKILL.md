---
name: daily
description: Use when the user asks to run, publish, backfill, or check today's FollowHub daily. Unless the user explicitly limits scope to one source, run both arXiv and RSS daily workflows and publish their completed results to the Follow page.
---

# Daily

Run FollowHub's two production daily pipelines as one coordinated workflow:

- `arxiv-daily`
- `rss-daily`

Do not interpret “daily” as arXiv-only or RSS-only. A source-specific request such as “run arXiv daily only” is the only reason to skip the other pipeline.

## Procedure

1. Resolve `FOLLOWHUB_CONFIG` or repo-local `followhub.yaml`.
2. Start raw acquisition for arXiv and RSS concurrently.
3. Run each pipeline according to its own `SKILL.md` contract:
   - `arxiv-daily`: collect → title-prefilter → filter → enrich → publish → verify
   - `rss-daily`: collect → normalize → fetch → dedupe → cluster → prefilter → filter → enrich → digest → publish → verify
4. Delegate all paper/item-level review and completion work to subagents. The main agent only orchestrates batches, validates and merges artifacts, invokes deterministic tools, and verifies publication.
5. Publish each completed pipeline independently. Same-day publish operations must preserve and merge the other source sections through the existing Follow publish path.
6. Verify the final page data contains both updates:
   - `follow/latest.json`
   - `follow/daily/YYYY-MM-DD.json`
   - affected `follow/sources/*.json`

## Retry Rule

When a worker times out, is unavailable, or emits invalid artifacts, keep that pipeline pending at its current stage and retry delegation with a fresh subagent. Do not replace worker judgments with main-agent decisions, `--auto-workers`, or heuristic production output. A successfully completed sibling pipeline may still publish while the other continues retrying.

## Reporting

Report the arXiv and RSS status separately, including raw counts, selected counts, published paths, verification result, and any pipeline still pending retries.
