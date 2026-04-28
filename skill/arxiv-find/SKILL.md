---
name: arxiv-find
description: Use when the user wants to search arXiv papers by keywords or topic context, generate daily briefs, or backfill missed daily briefs while keeping each day separate and limited to New submissions.
---

# arxiv-find

Hybrid arXiv retrieval for three jobs:

- daily brief generation
- backfill for missed days
- ad hoc keyword search

This skill keeps the daily-brief semantics strict: daily-style outputs should prefer **New submissions** and avoid mixing days together.

## Requirements Snapshot

- Support two entry paths:
  - scheduled daily runs
  - manual backfill after missed days
- If several days were missed, generate:
  - one brief per day
  - one backfill overview file
- Keep a shared YAML profile as the single source of truth.
- Reuse the same profile for scheduled and manual runs.
- Daily-style briefs should prefer **New submissions** only.
- Keyword search should still support pagination, filtering, and topic-context relevance hints.
- Support an `ArxivReader`-style `favorites` block for highlighted interest keywords.
- When multiple arXiv IDs need downstream enrichment, prefer orchestration plus subagent workers instead of one long inline pass.
- `arxiv-view` is a separate future skill for HTML rendering and is intentionally out of scope here.

## Design Pattern

Use a hybrid acquisition strategy instead of forcing one source to do every job:

1. `daily`
   - Prefer `arxiv.org/list/<category>/new`
   - Parse the official listing date
   - Extract only the `New submissions` section
   - Hydrate metadata via arXiv API by `id_list`

2. `backfill`
   - Use arXiv API with per-day `submittedDate` windows
   - Run one day at a time
   - Emit separate outputs for each day plus one overview

3. `search`
   - Use arXiv API query mode
   - Support category filters, keyword filters, exclude keywords, pagination, and simple relevance scoring

This split keeps the daily semantics accurate while preserving the stronger query and pagination capabilities of the API.

## Agent Role

`arxiv-find` is the main coordinator for the arXiv pipeline.

- Single-paper follow-up can stay inline.
- Multi-paper follow-up should prefer subagent fan-out.
- In those cases, `arxiv-enrich` is the default worker skill and `arxiv-find` stays responsible for deduplication, merge, and downstream handoff to `arxiv-view`.

## Shared Profile

Use one YAML profile file, for example:

```yaml
categories:
  - cs.RO
  - cs.AI

keywords:
  - vision-language-action
  - robot policy

exclude_keywords:
  - survey
  - medical

logic: AND

topic_context: |
  Real robot manipulation, VLA training recipes, and embodied policies.

favorites:
  enabled: true
  keywords:
    - "VLA"
  ignore_keywords:
    - "Medical"

daily:
  new_submissions_only: true
  max_results_per_day: 50

backfill:
  generate_overview: true
```

The skill includes an example file at `arxiv_profile.example.yaml`.

`favorites` follows the same spirit as `ArxivReader`: a lightweight highlight layer for especially important directions. It is not a separate config file.

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-find/arxiv_find.py help
python3 /home/tenstep/workspace/followhub/skill/arxiv-find/arxiv_find.py validate-profile --profile /path/to/arxiv-profile.yaml
python3 /home/tenstep/workspace/followhub/skill/arxiv-find/arxiv_find.py run --mode daily --profile /path/to/arxiv-profile.yaml
python3 /home/tenstep/workspace/followhub/skill/arxiv-find/arxiv_find.py run --mode backfill --profile /path/to/arxiv-profile.yaml --from-date 2026-04-24 --to-date 2026-04-27
python3 /home/tenstep/workspace/followhub/skill/arxiv-find/arxiv_find.py run --mode search --profile /path/to/arxiv-profile.yaml --keywords "vision-language-action,robot policy"
```

## Output Shape

- `daily`
  - one JSON file
  - one Markdown brief
- `backfill`
  - one JSON file and one Markdown brief per day
  - one Markdown overview that links the daily outputs
- `search`
  - one JSON result file
  - one Markdown digest-style listing

## Agent Workflow

1. Resolve the shared YAML profile path.
2. Choose mode: `daily`, `backfill`, or `search`.
3. Run the script.
4. Read the generated JSON and Markdown outputs.
5. If HTML browsing is needed later, hand off the result bundle to `arxiv-view`.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using the API alone for daily briefs | Prefer list-page `New submissions` semantics for daily mode |
| Merging missed days into one brief | Backfill must emit one brief per day plus one overview |
| Maintaining separate daily and manual configs | Use one shared YAML profile |
| Putting HTML rendering into this skill | Keep that in `arxiv-view` |
