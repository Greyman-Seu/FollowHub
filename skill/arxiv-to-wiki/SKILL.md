---
name: arxiv-to-wiki
description: Use when one or more arXiv papers should be turned into high-quality llm-wiki entries through the arxiv-to-wiki, paper-analyze, and llm-wiki pipeline, with post-write completeness checks and default publication to the R2 package and public wiki page unless the user explicitly opts out.
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
- an explicit publication opt-out such as `不发布`, `仅写入本地`, `只做草稿`, or `不要同步网站/R2`

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
-> validate wiki
-> build wiki package
-> package completeness-check loop
-> publish package to R2
-> refresh the public wiki data/page
-> verify the package and public source URLs
```

This is the default path for one new paper. Publishing is opt-out, not opt-in: do not ask whether to publish. The run is not complete until the source note and package-facing fields pass their checks, the package is published, and the public source page is reachable.

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

## Optional Structure-Maintenance Step

```text
arxiv-to-wiki
-> paper-analyze
-> llm-wiki
-> completeness-check loop
-> update-wiki
-> validate wiki
-> build package
-> package completeness-check loop
-> publish package to R2
-> publish-wiki
-> verify public URLs
```

Insert `update-wiki` when the user requests structure maintenance or when several closely related sources clearly justify promotion. Publication remains the default with or without this optional step. Publish only after the package-facing check passes.


## Data-Only Update Policy

For normal wiki content updates, update the wiki data source and R2 package only.
Do not commit repository code, generated page data, or submodule pointers unless the user explicitly asks to change code, layout, build scripts, schemas, or skill behavior.

Default content-update path:

```text
source note / topic / synthesis update
-> validate wiki
-> build wiki package
-> check package fields
-> sync package to R2
-> refresh website-facing data
-> verify the package manifest, source JSON, and public source page
```

Only use git commits for:

- page UI/layout changes
- skill or script changes
- package/schema changes
- explicit user request to commit repository state

This should mirror Follow data updates: the website reads cloud data, while the repo stays stable.

## Execution Rules

1. Resolve the input into one canonical arXiv paper reference.
   - for arXiv IDs, `abs` URLs, or `pdf` URLs, prefer the corresponding `html` page first
   - if the `html` page is unavailable or incomplete, fall back to `abs`, then to `pdf`
2. Resolve the target wiki root before doing any write operation.
3. If the paper already has a matching source note, refresh and reintegrate it by default without asking. Use attach-only behavior only when the user explicitly requests it.
4. Prefer this routing:
   - new paper, immediate ingest -> `direct`
   - new paper, preview first -> `draft`
   - source note already exists -> `attach`
5. Keep each downstream skill within its own responsibility boundary.
6. Do not duplicate paper synthesis inside this skill.
7. Do not duplicate topic/synthesis promotion logic inside this skill.
8. Publish the R2 package and refresh the website by default. Skip publication only when the current request explicitly says `不发布`, `仅写入本地`, `只做草稿`, `不要同步网站/R2`, or gives an equivalent opt-out.
9. After every source note write, run the source completeness checker for the produced slug.
10. If the checker reports missing required sections, labeled risk fields, source links, domain, tags, or related topics, edit the source note and rerun the checker until it passes.
11. Validate the wiki, build the website/R2 package, then run the checker again with `--package-dir`; missing `riskScenarios` or `riskJudgment` in JSON is a blocker.
12. Treat publication as a terminal condition, not a best-effort extra. After upload, verify that the package manifest, `source/<slug>.json`, and the public `/wiki/source/<slug>` page return successfully and correspond to the requested paper.
13. If a pre-existing validation error blocks publication, make a safe deterministic schema repair when possible and rerun validation. Otherwise report the exact publication blocker; never silently finish after only producing the local note.
14. Do not ask for routine confirmation before analysis or publication. Ask only when a material ambiguity cannot be resolved from the paper reference, configured wiki, or explicit mode.


## Completeness Check Loop

Run this loop after `paper-analyze` writes the source note, and again after the default package build. In explicit local-only or draft mode, the package-stage check may be deferred with publication.

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
- an explicit `hero_image` whenever the note contains a useful paper figure; `images` alone does not populate the page hero
- all stable paper sections from `paper-analyze`
- structured, reader-facing background and method blocks:
  - `**动机：**` and `**问题缺口：**`, each with at least 60 meaningful characters
  - `**方法概述：**` and `**核心机制：**`, each with at least 80 meaningful characters
  - `**方法拆解：**` with at least 3 concrete steps or components
  - `**关键要点：**` with at least 2 paper-specific takeaways
- `风险与判断` with explicit labeled blocks:
  - `**局限：**`
  - `**适用场景：**`
  - `**最终判断：**`
- package JSON fields after build:
  - `backgroundMotivation`
  - `backgroundGap`
  - `methodOverview`
  - `methodCore`
  - `methodBreakdown`
  - `methodTakeaways`
  - `riskLimitations`
  - `riskScenarios`
  - `riskJudgment`
  - `heroImage` when `figureGallery` is non-empty

These thresholds are a mechanical floor, not the writing target. Never pad a field or fill it with a placeholder merely to pass. Re-read the paper or existing note and add a concrete, paper-specific explanation that lets a reader understand why the work is needed and how it operates.

The bold labels above are the canonical authoring syntax and must be emitted verbatim by new runs. `### 动机` or `### 方法概述` is supported only as a legacy parser fallback; do not generate a mixture of headings and bold labels. Supplemental method subsections are allowed only after all four required method blocks are present.

## Recommended Working Patterns

- One paper, normal use:
  - `paper-analyze`
  - `llm-wiki`
  - validate, package, publish, and verify automatically
- Several new papers have accumulated:
  - run this skill per paper
  - if parallelism is available, use one worker per paper
  - later run `update-wiki`
- The user explicitly says not to publish:
  - stop after the requested local or draft artifacts and report that publication was intentionally skipped

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
- source and package completeness checks pass
- the request does not contain an explicit publication opt-out

## Success Criteria

A successful run should leave the system in one of these states:

- `direct`
  - one new or updated `wiki/sources/*.md` note exists
  - the note is integrated into the wiki structure
  - the R2 package contains the source JSON
  - the public `/wiki/source/<slug>` page is reachable and shows the requested paper
- `draft`
  - one draft note exists and is ready for review
  - publication is intentionally deferred until the draft is accepted
- `attach`
  - an existing source note is now properly connected into wiki structure
  - the refreshed package and public page are verified unless the user opted out

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating this skill as a replacement for `paper-analyze` | Keep single-paper reading and judgment in `paper-analyze` |
| Treating this skill as a replacement for `llm-wiki` | Keep knowledge-base maintenance in `llm-wiki` |
| Stopping after the local wiki note | Publish and verify R2 plus the public source page unless the user explicitly opted out |
| Asking whether to publish | Apply the persistent default automatically; ask only when the request explicitly selects draft or is materially ambiguous |
| Creating topics after every paper | Leave structural promotion to `update-wiki` unless there is an obvious immediate need |
| Lowering note depth for multi-paper runs | Keep the OpenVLA quality bar; reduce batch size rather than output quality |

## References

- Workflow examples and routing notes: [references/workflow.md](references/workflow.md)
