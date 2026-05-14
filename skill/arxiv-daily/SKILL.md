---
name: arxiv-daily
description: Use when the user asks for today's arXiv follow-up or missed-day arXiv backfill; this skill is an agent-native workflow that must execute collect -> title-prefilter -> filter -> enrich -> publish in order.
---

# arxiv-daily

Pipeline-level skill for daily arXiv follow-up.

`arxiv-daily` owns orchestration. It must not replace required stages with manual shortlisting.

`arxiv-daily` is a workflow skill, not a CLI-first skill.

- The primary entrypoint is this `SKILL.md`.
- The invoking agent should read this file, collect context, and run the workflow directly.
- Helper scripts may exist for artifact validation, merging, or local replay, but they are not the canonical user-facing entrypoint.
- The agent must not reinterpret missing worker outputs as permission to skip `arxiv-title-prefilter` or `arxiv-filter`.

## Non-Negotiable Execution Contract

For a normal daily run, the agent must execute these stages in order:

1. `arxiv-collect`
2. `arxiv-title-prefilter`
3. `arxiv-filter`
4. `arxiv-enrich` on selected papers only
5. `follow-publish`
6. publish verification

If any required step cannot be completed, the agent must stop and report the blocker instead of silently switching to a manual fallback.

## Hard Prohibitions

The agent must not:

- manually shortlist papers from raw `arxiv-collect` output as a substitute for `arxiv-title-prefilter` or `arxiv-filter`
- publish directly from raw `arxiv-collect` output
- skip `arxiv-filter` when `raw_count > 20`
- treat `arxiv-collect` built-in enrichment as a replacement for the explicit `arxiv-enrich` stage
- run `arxiv-enrich` on the full raw daily set
- run `follow-publish` before `filter_results.json` exists

## Skill Boundaries

- `arxiv-collect`
  - raw daily/backfill acquisition
  - may contain built-in metadata enrichment in current implementation
  - is still treated as raw acquisition for pipeline purposes
- `arxiv-title-prefilter`
  - title/category-only fast screening
  - outputs `keep` / `drop` / `uncertain`
- `arxiv-filter`
  - final include/exclude decision
  - owns `domains`, `one_liner_zh`, `summary_cn`, and `reason`
- `arxiv-enrich`
  - post-filter metadata completion for selected papers only
  - authors, affiliations, links, code/project URLs, English abstract normalization, score fields
  - emits agent-completion tasks for papers still missing `one_liner_zh` or `summary_cn`
- `follow-publish`
  - package and publish Follow JSON
- `rcli`
  - R2 verification

## Daily Procedure

1. Resolve config:
   - prefer `FOLLOWHUB_CONFIG`
   - otherwise use repo-local `followhub.yaml`
2. Run `arxiv-collect`.
3. Confirm daily `listing_date`.
4. If the target is "today" but `listing_date != today`, stop before publish by default.
5. Build title-prefilter batches from the raw daily JSON.
6. Use subagents or equivalent worker delegation to run `arxiv-title-prefilter`, usually in batches.
7. Merge all prefilter outputs into `prefilter_results.json`.
8. Build full filter batches from all `keep` and `uncertain` papers.
9. Use subagents or equivalent worker delegation to run `arxiv-filter`, usually in batches.
10. Merge all filter outputs into `filter_results.json`.
11. Retry `arxiv-filter` for selected papers that still lack `one_liner_zh` or `summary_cn`.
12. Build enrich inputs from `include_in_follow=true` papers only.
13. Run `arxiv-enrich` on the selected subset only.
14. If `arxiv-enrich` reports agent-completion tasks, the invoking agent must complete them before publish.
15. Merge filter + enrich results into the final daily digest.
16. Run `follow-publish`.
    - default behavior is to publish to R2 when the workflow succeeds
    - only skip remote publish when the user explicitly asks for local-only output
17. Verify:
    - `follow/latest.json`
    - `follow/daily/YYYY-MM-DD.json`
    - `follow/sources/arxiv.json`

## Required Artifacts

A successful daily run must produce all of the following:

- raw daily JSON from `arxiv-collect`
- `prefilter_results.json`
- `filter_results.json`
- `enrich_input.json`
- `enrich_results.json`
- final daily digest JSON
- publish output metadata
- verification output metadata

Missing required artifacts are a failed run, not a warning.

## Subagent Policy

Batching belongs here, not in worker skills.

Recommended defaults:

- `raw_count > 20`
  - title-prefilter is mandatory
- `keep` and `uncertain`
  - both advance to `arxiv-filter`
- `drop`
  - must not advance to `arxiv-filter`
- more than 5 full-filter papers
  - batch `arxiv-filter` in groups of 3-5 papers
- enrich only selected papers after filtering

Subagents are the recommended execution mode for `arxiv-title-prefilter` and `arxiv-filter`.
The contract is stage order and artifacts, not a specific concurrency model.

The invoking agent should normally:

- split title-prefilter into batches
- delegate those batches to workers
- merge worker outputs into `prefilter_results.json`
- split full-filter work into batches
- delegate those batches to workers
- merge worker outputs into `filter_results.json`

If a local helper script is used, it should support this workflow rather than replace it with blocking "write this file and rerun" instructions.

Each title-prefilter worker returns:

```json
{
  "items": [
    {
      "arxiv_id": "2605.xxxxx",
      "decision": "keep",
      "reason": "标题直接属于 VLA / 机器人操作主线。"
    }
  ]
}
```

Each `arxiv-filter` worker returns:

```json
{
  "items": [
    {
      "arxiv_id": "2605.xxxxx",
      "include_in_follow": true,
      "domains": [
        {"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}
      ],
      "one_liner_zh": "一句话说明论文核心贡献。",
      "summary_cn": "英文摘要的中文翻译，保持事实一致，不要额外发挥。",
      "reason": "纳入或排除原因。"
    }
  ]
}
```

## Publish Rules

- Publish only `include_in_follow=true` papers.
- Successful daily runs should publish to R2 by default.
- If a paper has no filter result, keep it out of the published shortlist unless the user explicitly asks for raw publishing.
- If a selected paper is missing `one_liner_zh` or `summary_cn`, retry `arxiv-filter` first.
- If fields are still missing after filter retry, `arxiv-enrich` should expose agent-completion tasks for those papers.
- If the invoking agent does not complete those tasks, publishing may proceed only when the user accepts incomplete output.
- If `listing_date != today` for a "today" run, the agent should call that out clearly. Publishing may still proceed when the user asked to run today's available arXiv update or when `allow_stale_listing` is explicitly accepted.
- R2 deletion and purge are not part of the daily path.

## Helper Script Surface

```text
arxiv-daily/run_daily.py
  -> arxiv-collect
  -> may write prefilter/filter artifacts for local replay or validation
  -> selected-only arxiv-enrich stage
  -> agent completion for enrich-reported missing Chinese fields
  -> follow-publish
  -> rcli verification
```

This script is a helper, not the primary contract.
