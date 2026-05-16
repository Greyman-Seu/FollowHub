---
name: arxiv-enrich
description: Use when arXiv result files need stable summary, affiliation, score, and link fields, or when arxiv-find needs its default post-retrieval enrichment phase.
---

# arxiv-enrich

Enrich `arxiv-find` result payloads into the shared FollowHub arXiv data contract.

## Invocation Model

- This skill is meant to be installed into Codex / Claude and invoked by an agent.
- The Python CLI is the stable tool surface that the agent calls internally.
- The CLI is not intended to be the primary human-facing workflow.

## Requirements Snapshot

- Work as a standalone skill on existing result files.
- Also serve as the default internal enrichment phase behind `arxiv-find`.
- Guarantee contract fields even when values are empty.
- Prefer local heuristics first so the skill still works without network access.
- Leave room for future stronger enrichment passes.
- When multiple paper IDs are involved, expect to be used as a worker by a higher-level orchestrator rather than as the conversation entry point.

## Responsibilities

- `relevance_score` with shared profile semantics
- `abstract_en`
- `one_liner_zh`
- `summary_cn`
- `first_affiliation` and `affiliations`
- `related_organizations` and `related_companies`
- `code_urls` and `project_urls`
- `recency_score`, `hot_score`, `quality_score`, `overall_score`

## Agent Tool Surface

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-enrich/arxiv_enrich.py help
python3 /home/tenstep/workspace/followhub/skill/arxiv-enrich/arxiv_enrich.py enrich --input /path/to/arxiv-find.json --output /path/to/enriched.json
python3 /home/tenstep/workspace/followhub/skill/arxiv-enrich/arxiv_enrich.py enrich --input /path/to/arxiv-find.json --profile /path/to/arxiv-profile.yaml --output /path/to/enriched.json
```

## Notes

- Phase 1 enrichment is heuristic-first.
- Missing enrich values still produce present fields with empty or zero defaults.
- Retrieval stays in `arxiv-find`.
- In agent-native usage, `arxiv-enrich` is usually the worker and `arxiv-find` is the coordinator.
- When a shared profile is provided, `arxiv-enrich` recomputes `relevance_score` using keyword/category/favorites semantics compatible with `arxiv-find`, while also borrowing `evil-read-arxiv` style recency and recommendation heuristics.
- `one_liner_zh` and `summary_cn` should not rely on API calls inside this script.
- When Chinese text or related organizations are missing, the output should expose structured agent-completion tasks so the invoking agent can fan out subagents and fill them.

## Two-Phase Contract

`arxiv-enrich` is intentionally split into two phases:

1. CLI/local phase
   - normalize `abstract_en`
   - enrich affiliations, author metadata, related organizations/companies, code/project links, and scores
   - preserve existing `one_liner_zh` and `summary_cn` when present
   - emit `needs_agent_summary` and prompt fields when Chinese text is missing
   - emit `needs_related_organizations` and `agent_organization_prompt` when organization metadata is missing

2. Agent completion phase
   - the invoking agent reads `agent_completion.tasks`
   - parallelizes them with subagents when several papers are missing Chinese fields or organizations
   - merges returned `one_liner_zh`, `summary_cn`, `related_organizations`, and `related_companies` back into the enrich result

`arxiv-enrich` owns this second-stage handoff contract. Higher-level orchestrators such as `arxiv-daily` should treat `arxiv-enrich` as the stage responsible for exposing these agent tasks, rather than re-deriving prompts themselves.

## Output Handoff

When agent completion is still required, the enriched payload should include:

```json
{
  "agent_completion": {
    "required": true,
    "task_count": 2,
    "recommended_batch_size": 3,
    "recommended_worker": "arxiv-enrich-agent-completion",
    "tasks": [
      {
        "arxiv_id": "2605.xxxxx",
        "agent_summary_prompt": "...",
        "expected_output_schema": {
          "arxiv_id": "2605.xxxxx",
          "one_liner_zh": "string",
          "summary_cn": "string",
          "related_organizations": ["string"],
          "related_companies": ["string"]
        }
      }
    ]
  }
}
```
