---
name: rss-enrich
description: Use when RSS result files need stable author, link, source, and summary fields, or when missing Chinese text should be handed off to agent completion tasks.
---

# rss-enrich

Enrich RSS items into the shared FollowHub contract.

## Invocation Model

- This skill is meant to be installed into Codex / Claude and invoked by an agent.
- The Python CLI is the stable tool surface that the agent calls internally.

## Two-Phase Contract

1. CLI/local phase
   - normalize links, author, source labels, tags, content text
   - preserve existing `one_liner_zh` and `summary_cn`
   - emit agent completion tasks for missing Chinese fields

2. Agent completion phase
   - the invoking agent reads `agent_completion.tasks`
   - parallelizes them with subagents when several items are missing Chinese fields
   - merges returned `one_liner_zh` and `summary_cn` back into the enrich result
   - for `x` and `wechat`, production results should be agent-authored rather than RSS-summary-derived or rule-derived

The repository-level helper for batching these tasks is:

```bash
python3 skill/rss-daily/agent_batch_runner.py plan-enrich --input rss-daily-output/<date>/enrich_results.json --output-dir rss-daily-output/<date>/agent-batches/enrich
python3 skill/rss-daily/agent_batch_runner.py merge-enrich --input rss-daily-output/<date>/enrich_results.json --batch-dir rss-daily-output/<date>/agent-batches/enrich --output rss-daily-output/<date>/enrich_results.json
```


## X / Twitter Summary Quality Gate

For `x` items, `one_liner_zh` is production-ready only if it carries concrete information. It must not be a generic activity label such as “分享了一条值得查看的动态”, “转发并评论了一条值得关注的动态”, “分享了一段演示或产品展示”, or “分享了一项研究进展”.

A good X summary should name the product/model/paper/person or state the concrete claim, capability, result, or viewpoint. If the available feed text is insufficient, emit an agent completion task instead of accepting a placeholder.

## Production Rule

- For `x` and `wechat`, treat `one_liner_zh` / `summary_cn` as production-ready only when the merged result explicitly carries `summary_generated_by: agent`.
- Rule-based or feed-derived placeholders are acceptable only in smoke-test paths, not for production publish.

## Agent Tool Surface

```bash
python3 skill/rss-enrich/rss_enrich.py help
python3 skill/rss-enrich/rss_enrich.py enrich --input rss-daily-output/2026-05-12/filter_input.json --output rss-daily-output/2026-05-12/enrich_results.json
```
