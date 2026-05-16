---
name: arxiv-to-wiki
description: Use when one or more arXiv papers should be turned into high-quality llm-wiki entries through the arxiv-to-wiki -> paper-analyze -> llm-wiki pipeline, with post-write completeness checks, optional batch subagent parallelism, and optional website/R2 sync.
---

# arxiv-to-wiki

Turn arXiv papers into maintained knowledge-base entries without losing downstream wiki fields.

This skill is a thin orchestration layer. It should not reimplement paper analysis, wiki maintenance, or website sync logic.

## When To Use

Use this skill when:

- the user gives one arXiv URL or one arXiv ID
- the goal is not just to read the paper, but to absorb it into `llm-wiki`
- the user says things like:
  - `把这篇 arXiv 加进知识库`
  - `分析这篇论文并沉淀到 wiki`
  - `先分析论文，再同步到我的知识库`

Do not use this skill for:

- arXiv daily collection or batch screening
- non-arXiv sources as the primary entrypoint
- direct website-only sync without wiki integration

## Role Split

- `arxiv-to-wiki`
  - owns orchestration only
  - decides which downstream skill sequence to run
- `paper-analyze`
  - deeply analyzes one paper
  - writes one wiki-ready source note
- `llm-wiki`
  - integrates the note into the knowledge base structure
  - updates source, topic, entity, index, log, and overview layers as needed
- `update-wiki`
  - periodically promotes repeated source clusters into topic or synthesis pages
- `publish-wiki`
  - syncs already-written wiki content into the website layer

## Inputs

Required:

- one arXiv URL such as `https://arxiv.org/abs/2605.05241`
  or one arXiv ID such as `2605.05241`
- target `llm-wiki` root

Optional:

- output mode
- whether to preview first
- whether to reorganize the wiki after ingest
- whether to publish website-facing data after ingest

## Modes

### `direct`

- default
- analyze the paper
- write the source note into `wiki/sources`
- integrate it into the wiki immediately

### `draft`

- analyze the paper into a draft note first
- do not commit to wiki structure until the user confirms

### `attach`

- use when a source note already exists
- skip paper analysis
- only integrate and organize around the existing note

## Multi-Paper Handling

If the user gives multiple papers, use the same arxiv-to-wiki path for every paper. When subagents are available and the user requested batch processing, parallelize with one worker per paper.

- each worker owns one paper only
- each worker uses `paper-analyze` depth and produces one source note only
- workers may write only their assigned `wiki/sources/<slug>.md` file or a draft file
- workers must report the exact source slug/path they produced
- the main agent remains responsible for:
  - deduplication
  - wiki write coordination
  - topic/synthesis/index/log updates
  - package build and website/R2 sync
  - final completeness review for every produced slug

Do not hand the whole batch to one worker.
Do not let workers race on shared wiki structure files.
Do not lower note quality because the run is batched.

## Default Pipeline

```text
arxiv-to-wiki
-> paper-analyze
-> llm-wiki
-> completeness-check loop
```

This is the default path for one new paper. The run is not complete until the source note and package-facing fields pass the completeness check.

## Quality Standard

`arxiv-to-wiki` inherits the strong note standard from `paper-analyze`.

This means:

- one paper or many papers does not change the expected note depth
- multi-paper runs may parallelize, but may not downgrade outputs into thin summary cards
- each worker should still target an `OpenVLA`-level source note:
  - strong `背景与问题`
  - real `方法` decomposition
  - concrete `结果`
  - non-generic `洞察`
  - figures when useful
  - a result table when the source supports it

If the batch is too large to maintain that quality, reduce batch size or concurrency instead of lowering standards.

## Optional Extended Pipeline

```text
arxiv-to-wiki
-> paper-analyze
-> llm-wiki
-> completeness-check loop
-> update-wiki
-> build package
-> package completeness-check loop
-> publish-wiki
```

Use the extended path when the user wants structure maintenance, website sync, or R2 sync. Publish only after the package-facing check passes.

## Execution Rules

1. Resolve the input into one canonical arXiv paper reference.
   - for arXiv IDs, `abs` URLs, or `pdf` URLs, prefer the corresponding `html` page first
   - if the `html` page is unavailable or incomplete, fall back to `abs`, then to `pdf`
2. Resolve the target wiki root before doing any write operation.
3. If the paper already has a matching source note:
   - ask whether to refresh the note or just attach and reorganize around it
4. Prefer this routing:
   - new paper, immediate ingest -> `direct`
   - new paper, preview first -> `draft`
   - source note already exists -> `attach`
5. Keep each downstream skill within its own responsibility boundary.
6. Do not duplicate paper synthesis inside this skill.
7. Do not duplicate topic/synthesis promotion logic inside this skill.
8. Do not run website sync unless the user asked for it.
9. After every source note write, run the source completeness checker for the produced slug.
10. If the checker reports missing required sections, labeled risk fields, source links, domain, tags, or related topics, edit the source note and rerun the checker until it passes.
11. After building a package for website/R2 sync, run the checker again with `--package-dir`; missing `riskScenarios` or `riskJudgment` in JSON is a blocker.


## Completeness Check Loop

Run this loop after `paper-analyze` writes the source note, and again after package build when website/R2 sync is requested.

```bash
python3 skill/arxiv-to-wiki/scripts/check_source_completeness.py \
  --wiki-root /path/to/llm-wiki \
  --slug <source-slug>
```

After building the FollowHub wiki package:

```bash
python3 skill/arxiv-to-wiki/scripts/check_source_completeness.py \
  --wiki-root /path/to/llm-wiki \
  --package-dir /tmp/followhub-wiki-package \
  --slug <source-slug>
```

The loop must pass before the task is considered done. Fix the source note and rerun if any required field is missing.

Required source-note fields include:

- frontmatter source type, source URL, date, domain, tags, related topics, and status
- all stable paper sections from `paper-analyze`
- `风险与判断` with explicit labeled blocks:
  - `**局限：**`
  - `**适用场景：**`
  - `**最终判断：**`
- package JSON fields after build:
  - `riskLimitations`
  - `riskScenarios`
  - `riskJudgment`

Never fill a missing field with a placeholder. Re-read the paper or existing note and add the missing interpretation.

## Recommended Working Patterns

- One paper, normal use:
  - `paper-analyze`
  - `llm-wiki`
- Several new papers have accumulated:
  - run this skill per paper
  - if parallelism is available, use one worker per paper
  - later run `update-wiki`
- The user wants the public page refreshed:
  - run `publish-wiki` after wiki updates stabilize

## Handoff Contract

Before invoking `paper-analyze`, ensure:

- the paper reference is specific
- the target wiki root is known

Before invoking `llm-wiki`, ensure:

- there is a source note to ingest or attach
- the active wiki root is the intended one

Before invoking `update-wiki`, ensure:

- several source notes now exist
- the user wants structural cleanup, topic promotion, or synthesis pages

Before invoking `publish-wiki`, ensure:

- the wiki content already exists and is the source of truth
- the user wants website-facing data refreshed

## Success Criteria

A successful run should leave the system in one of these states:

- `direct`
  - one new or updated `wiki/sources/*.md` note exists
  - the note is integrated into the wiki structure
- `draft`
  - one draft note exists and is ready for review
- `attach`
  - an existing source note is now properly connected into wiki structure

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating this skill as a replacement for `paper-analyze` | Keep single-paper reading and judgment in `paper-analyze` |
| Treating this skill as a replacement for `llm-wiki` | Keep knowledge-base maintenance in `llm-wiki` |
| Auto-running `publish-wiki` every time | Only sync the website when the user asks |
| Creating topics after every paper | Leave structural promotion to `update-wiki` unless there is an obvious immediate need |
| Lowering note depth for multi-paper runs | Keep the OpenVLA quality bar; reduce batch size rather than output quality |

## References

- Workflow examples and routing notes: [references/workflow.md](references/workflow.md)
