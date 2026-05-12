---
name: arxiv-daily
description: Use when the user asks for today's arXiv follow-up or missed-day arXiv backfill; this skill must execute the explicit collect -> title-prefilter -> filter -> enrich -> publish chain and must stop on missing required steps.
---

# arxiv-daily

Pipeline-level skill for daily arXiv follow-up.

`arxiv-daily` owns orchestration. It must not replace required stages with manual shortlisting.

## Required Entry Point

Normal daily execution must use the orchestrator:

```bash
python3 skill/arxiv-daily/run_daily.py daily --config followhub.yaml
```

Backfill execution must also use the orchestrator:

```bash
python3 skill/arxiv-daily/run_daily.py backfill --config followhub.yaml --from-date 2026-05-01 --to-date 2026-05-03
```

The agent must not improvise a different normal execution path when this orchestrator is available.

The orchestrator is artifact-driven:

- it may call tool-type skills such as `arxiv-collect`, `arxiv-enrich`, and `follow-publish`
- it must not replace `arxiv-title-prefilter` or `arxiv-filter` with built-in heuristic Python decisions
- when those worker-stage results are absent, it should stop and ask the invoking agent to complete the worker stage and write the required artifact

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
6. Run `arxiv-title-prefilter`, usually in batches.
7. Merge all prefilter outputs into `prefilter_results.json`.
8. Build full filter batches from all `keep` and `uncertain` papers.
9. Run `arxiv-filter`, usually in batches.
10. Merge all filter outputs into `filter_results.json`.
11. Retry `arxiv-filter` for selected papers that still lack `one_liner_zh` or `summary_cn`.
12. Build enrich inputs from `include_in_follow=true` papers only.
13. Run `arxiv-enrich` on the selected subset only.
14. If `arxiv-enrich` reports agent-completion tasks, the invoking agent must complete them before publish.
15. Merge filter + enrich results into the final daily digest.
16. Run `follow-publish`.
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

Subagents are optional optimization for `arxiv-title-prefilter`, `arxiv-filter`, and `arxiv-enrich`.
The contract is stage order and artifacts, not a specific concurrency model.

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
- If a paper has no filter result, keep it out of the published shortlist unless the user explicitly asks for raw publishing.
- If a selected paper is missing `one_liner_zh` or `summary_cn`, retry `arxiv-filter` first.
- If fields are still missing after filter retry, `arxiv-enrich` should expose agent-completion tasks for those papers.
- If the invoking agent does not complete those tasks, publishing may proceed only when the user accepts incomplete output.
- If `listing_date != today` for a "today" run, default behavior is to skip publish rather than duplicate the previous listing.
- R2 deletion and purge are not part of the daily path.

## Current Orchestrator Surface

```text
arxiv-daily/run_daily.py
  -> arxiv-collect
  -> writes prefilter_input.json, waits for arxiv-title-prefilter results
  -> writes filter_input.json, waits for arxiv-filter results
  -> selected-only arxiv-enrich stage
  -> agent completion for enrich-reported missing Chinese fields
  -> follow-publish
  -> rcli verification
```
