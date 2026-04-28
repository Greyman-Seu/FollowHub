---
name: arxiv-enrich
description: Use when arXiv result files need stable summary, affiliation, score, and link fields, or when arxiv-find needs its default post-retrieval enrichment phase.
---

# arxiv-enrich

Enrich `arxiv-find` result payloads into the shared FollowHub arXiv data contract.

## Requirements Snapshot

- Work as a standalone skill on existing result files.
- Also serve as the default internal enrichment phase behind `arxiv-find`.
- Guarantee contract fields even when values are empty.
- Prefer local heuristics first so the skill still works without network access.
- Leave room for future stronger enrichment passes.
- When multiple paper IDs are involved, expect to be used as a worker by a higher-level orchestrator rather than as the conversation entry point.

## Responsibilities

- `abstract_en`
- `one_liner_zh`
- `summary_cn`
- `first_affiliation` and `affiliations`
- `code_urls` and `project_urls`
- `hot_score`, `quality_score`, `overall_score`

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-enrich/arxiv_enrich.py help
python3 /home/tenstep/workspace/followhub/skill/arxiv-enrich/arxiv_enrich.py enrich --input /path/to/arxiv-find.json --output /path/to/enriched.json
```

## Notes

- Phase 1 enrichment is heuristic-first.
- Missing enrich values still produce present fields with empty or zero defaults.
- Retrieval stays in `arxiv-find`.
- In agent-native usage, `arxiv-enrich` is usually the worker and `arxiv-find` is the coordinator.
- `one_liner_zh` and `summary_cn` should not rely on API calls inside this script.
- When those fields are missing, the output should expose a prompt so the invoking agent can fill them.
