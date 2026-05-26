---
name: update-wiki
description: Use when FollowHub needs to periodically review llm-wiki source notes, identify repeated themes, promote stable clusters into topic or synthesis notes, and refresh knowledge-base entry points like purpose.md and index.md.
---

# update-wiki

Periodically reorganize `llm-wiki` so that accumulated `sources/` notes grow into a cleaner topic and synthesis structure.

This skill is not for analyzing one new paper.  
It is for revisiting existing notes and improving the structure of the knowledge base.

## When To Use

Use this skill when:

- several new paper notes have been written into `wiki/sources/`
- the user asks to “梳理知识库”, “更新 wiki”, “整理 sources”, “提炼 topic”, or “做一轮总结”
- the user wants to know which repeated themes deserve topic pages
- the knowledge base has grown, but `topics/`, `synthesis/`, `index.md`, or `purpose.md` are lagging behind

Do not use this skill as a replacement for `paper-analyze`.

## Role Split

- `paper-analyze`
  - analyzes one paper
  - writes one structured source note
- `update-wiki`
  - reviews many existing source notes
  - clusters related notes
  - proposes or writes topic/synthesis updates
- `wiki-sync-page`
  - syncs already-written wiki content into the website layer

## Inputs

Required:

- configured `llm-wiki` root

Typical working set:

- `wiki/sources/*.md`
- existing `wiki/topics/*.md`
- existing `wiki/synthesis/*.md`
- `purpose.md`
- `index.md`

## Output Goal

This skill should help the knowledge base evolve along:

```text
source note -> topic note -> synthesis note -> refreshed index / purpose
```

## Core Questions

For each run, answer:

1. Which recent source notes belong to the same theme?
2. Which themes are now stable enough to deserve a topic page?
3. Which existing topics need to be updated with new source notes?
4. Which topic clusters are now rich enough for a synthesis page?
5. Does `index.md` or `purpose.md` need updating to reflect the new center of gravity?

## Workflow

### 1. Review recent sources

- read recently added or recently relevant notes in `wiki/sources/`
- identify repeated vocabulary, repeated methods, repeated benchmarks, or repeated problem settings
- you may first run:
  - `python3 skill/update-wiki/scripts/update_wiki.py --wiki-root <path> --print-json`
  - to get a lightweight source digest queue before deeper clustering

### 2. Cluster by theme

Look for:

- the same technical route appearing across multiple papers
- a method family starting to form
- repeated comparison targets
- repeated “why this matters” observations

### 3. Decide source vs. topic vs. synthesis

Use this rule of thumb:

- one paper only -> stay in `sources`
- 3-5 related papers -> create or update a `topic`
- stable disagreement, evolution, or cross-paper comparison -> create or update a `synthesis`

### 4. Update or create topic pages

For a new or stale topic, capture:

- what the topic is really about
- why it matters
- the core question
- which source notes belong under it

### 5. Update or create synthesis pages

Do this when there is enough accumulated material to compare:

- different method routes
- open vs. closed approaches
- scaling vs. fine-tuning strategies
- engineering tradeoffs

### 6. Refresh entry points

Update when needed:

- `index.md`
- `purpose.md`

Only do this if the knowledge base emphasis has genuinely shifted.

## Writing Style

- Prefer structural clarity over volume.
- Do not produce broad, empty overviews.
- Keep topic pages narrower than synthesis pages.
- When updating `purpose.md`, adjust only what has actually changed in research focus.

## Practical Heuristics

- If a note is still isolated, leave it in `sources`
- If multiple papers repeat the same core pattern, elevate it into a topic
- If you can articulate “Route A vs. Route B”, that is often synthesis-worthy
- Avoid creating too many thin topics

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating every new source as a new topic | Wait for repeated structure across several sources |
| Writing long topic pages that are really syntheses | Keep topic pages scoped; move higher-level comparison into synthesis |
| Updating the website directly | Keep this skill inside `llm-wiki`; use `wiki-sync-page` later |
| Re-analyzing papers from scratch | Reuse source notes as the source of truth |

## Minimal Success Criteria

A good `update-wiki` run should usually do at least one of:

- update one existing topic with new source notes
- create one new topic from repeated source clusters
- create one synthesis note from multiple topics or routes
- refresh `index.md` to reflect the new best entry points
