---
name: arxiv-daily
description: Use when the user asks for today's arXiv follow-up or missed-day arXiv backfill; this is a prompt-only pipeline skill that orchestrates arxiv-collect, arxiv-filter, arxiv-enrich, follow-publish, and rcli.
---

# arxiv-daily

Pipeline-level skill for daily arXiv follow-up.

`arxiv-daily` is an agent procedure, not a Python product surface. It should not own deterministic implementation logic. Use the lower-level skills and their tools for actual work.

## Role

When the user says something like:

```text
/arxiv-daily 帮我统计今天信息
```

the agent should run the full pipeline:

1. Collect raw arXiv papers.
2. Filter raw papers with subagents.
3. Enrich selected papers with subagents.
4. Merge results into a Follow digest.
5. Publish the digest to R2/page.
6. Verify the published JSON and page source.

## Skill Boundaries

- `arxiv-collect`
  - raw daily/backfill acquisition
  - no semantic filtering
- `arxiv-filter`
  - worker skill for include/exclude, domains, one-line Chinese summary, Chinese summary, and reason
  - accepts one paper or a small batch
- `arxiv-enrich`
  - worker skill for selected paper details
  - authors, affiliations, links, code/project URLs, English abstract normalization, score fields
  - not the owner of Chinese summary generation
- `follow-publish`
  - package and publish Follow JSON
- `rcli`
  - R2 upload/list verification

## Daily Procedure

1. Resolve config:
   - prefer `FOLLOWHUB_CONFIG`
   - otherwise use repo-local `followhub.yaml`
2. Use `arxiv-collect` to run daily raw collection.
3. Confirm raw count is category-wide and comparable to `ArxivReader` semantics.
4. Build filter tasks from the raw daily JSON.
5. Spawn `arxiv-filter` subagents in batches.
6. Merge all worker outputs into `filter_results.json`.
7. If any selected paper still has missing `one_liner_zh` or `summary_cn`, retry `arxiv-filter` for those papers first.
8. Use the selected IDs from `filter_results.json` to run `arxiv-enrich` workers.
9. Merge filter and enrich results into a Follow daily digest.
10. Use `follow-publish` to publish to the configured R2 prefix, normally `follow/`.
11. Verify:
    - `follow/latest.json`
    - `follow/daily/YYYY-MM-DD.json`
    - `follow/sources/arxiv.json`

## Backfill Procedure

Use the same shape as daily, but `arxiv-collect` should run backfill by date window.

Backfill must preserve one digest per date.

Publishing historical days is maintenance behavior. When using `follow-publish`, historical writes must be explicit through its safety flags.

## Subagent Policy

Subagent orchestration belongs here, not in worker skills.

Recommended defaults:

- 1-5 raw papers: the main agent may run `arxiv-filter` directly.
- More than 5 raw papers: spawn `arxiv-filter` workers in groups of 3-5 papers.
- Enrich only selected papers after filtering.
- Do not enrich the full raw daily set.

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
- If Chinese summary fields still remain missing after retry, the paper may still be published, but this should be treated as an incomplete follow item and tracked for later repair.
- Do not use static keyword rules as the final Follow decision.
- R2 deletion and purge are not part of the daily path.

## Current Production Chain

```text
arxiv-daily
  -> arxiv-collect
  -> arxiv-filter
  -> arxiv-enrich
  -> follow-publish
  -> rcli
```
