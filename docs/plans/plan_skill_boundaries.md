# FollowHub Skill Boundaries

This note defines the intended boundaries between the current skills and the next agent-native workflow.

## Target Mental Model

The daily arXiv flow should be:

1. `arxiv-collect` collects raw papers.
2. `arxiv-daily` fans out `arxiv-filter` work to subagents.
3. `arxiv-filter` workers decide inclusion, domains, and summaries.
4. Selected papers are enriched in parallel through `arxiv-enrich`.
5. `follow-publish` packages and publishes the final shortlist.

Rules may still create cheap metadata such as ordering hints, but rules should not decide the final Follow shortlist.

## arxiv-collect

Current role:

- Retrieve arXiv data.
- Keep daily semantics close to `ref/ArxivReader`:
  - `daily` uses `arxiv.org/list/<category>/new`.
  - It parses `New submissions`.
  - It hydrates metadata through the arXiv API `id_list` path.
- Keep backfill separate:
  - `backfill` uses arXiv export API submitted-date windows.
  - It writes one daily result per date.

Target boundary:

- `arxiv-collect` should be the raw acquisition skill.
- It should not make the final include/exclude decision for Follow.
- It may attach cheap hints:
  - `source_categories`
  - `matched_keywords`
  - `context_hits`
  - `relevance_score`
- Those hints are inputs for the agent, not final filtering decisions.

Important correction:

- Daily raw output should not be capped to a small candidate pool before agent review.
- For categories such as `cs.RO`, `cs.AI`, and `cs.LG`, raw daily volume should be comparable to `ArxivReader` category daily results.

## arxiv-enrich

Current role:

- Normalize and enrich arXiv result fields.
- Fill stable contract fields:
  - `abstract_en`
  - `authors`
  - `first_affiliation`
  - `code_urls`
  - `project_urls`
  - score fields
  - empty placeholders for missing summaries

Target boundary:

- `arxiv-enrich` should behave like a single-paper worker.
- A higher-level agent should call it in parallel for selected papers.
- It should not be the daily entrypoint.
- It should not decide whether a paper belongs in Follow.
- Chinese summaries and one-line conclusions should be filled by the agent/subagent, not by API calls embedded in this script.

## arxiv-daily

Current role:

- High-level arXiv daily procedure.
- Coordinates lower-level skills through agent instructions.

Target boundary:

- `arxiv-daily` is the user-facing pipeline skill.
- When the user says "help me summarize today's arXiv", this skill should orchestrate the run.
- It is prompt-only. Lower-level skills own deterministic tools.
- The invoking agent owns subagent fan-out.

Expected agent-native flow:

1. Use `arxiv-collect` to collect daily raw papers.
2. Read `filter_tasks.json`.
3. Spawn `arxiv-filter` subagents in batches.
4. Merge subagent JSON into `filter_results.json`.
5. Run `arxiv-enrich` only for selected papers.
6. Use `follow-publish` to publish the merged digest.

The filter result should include:

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

## follow-publish

Current role:

- Convert Follow daily digests into page-ready JSON.
- Maintain the R2 object shape:
  - `follow/latest.json`
  - `follow/manifest.json`
  - `follow/domains.json`
  - `follow/daily/YYYY-MM-DD.json`
  - `follow/sources/arxiv.json`
  - `follow/sources/x.json`
  - `follow/sources/wechat.json`
  - `follow/sources/bilibili.json`

Target boundary:

- `follow-publish` is a packaging and publishing skill.
- It should not classify papers.
- It should not infer domains from rules.
- If no agent result exists, `Uncategorized` is an explicit fallback state.
- It should publish only `include_in_follow=true` items into source indexes.

Safety boundary:

- Daily publish should not delete remote data.
- Historical daily writes require explicit maintenance intent through `--allow-historical`.
- Destructive R2 operations belong outside the default daily path.

## arxiv-view

Current role:

- Local/static viewer for arXiv result JSON.
- Good for preview and debugging.

Target boundary:

- It is not the production publishing layer.
- Production Follow pages read R2 JSON through the page repo.
- `arxiv-view` remains useful for local inspection of raw and enriched results.

## rcli

Current role:

- Thin R2/rclone wrapper.

Target boundary:

- Upload and list R2 objects.
- Avoid destructive commands in daily paths.
- Deletion and purge should be treated as maintenance-only actions.

## arxiv-fig

Current role:

- Extract figures from papers.

Target boundary:

- Optional downstream worker for selected papers.
- Not part of the mandatory daily publish path yet.

## Future Convenience

The intended single user action is:

```text
/arxiv-daily 帮我统计今天信息
```

The invoking agent should then:

1. Use `arxiv-daily` to collect raw daily papers through `arxiv-collect`.
2. Use `arxiv-filter` subagents to process batches from `filter_tasks.json`.
3. Merge subagent outputs into `filter_results.json`.
4. Use `arxiv-enrich` on selected papers only.
5. Use `follow-publish` to publish the merged digest.
6. Verify R2 `follow/` JSON and the Follow page.

For token efficiency, each subagent should handle 3-5 papers and combine:

- include/exclude decision
- domain classification
- one-line Chinese summary
- Chinese summary

For selected papers that need deeper metadata work, the main agent should then fan out `arxiv-enrich` workers per paper or per small batch.

Do not run `arxiv-enrich` across the full raw daily set. The intended order is filter first, enrich selected papers second.

## Open Implementation Items

- Keep `arxiv-collect` raw daily aligned with `ArxivReader` category daily volume.
- Keep `filter_tasks.json` as the worker batch contract for subagent fan-out.
- Add a merge helper for subagent result fragments.
- Make `arxiv-enrich` clearer as a single-paper worker in both docs and code.
