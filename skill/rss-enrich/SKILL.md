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

## Agent Tool Surface

```bash
python3 skill/rss-enrich/rss_enrich.py help
python3 skill/rss-enrich/rss_enrich.py enrich --input rss-daily-output/2026-05-12/filter_input.json --output rss-daily-output/2026-05-12/enrich_results.json
```
