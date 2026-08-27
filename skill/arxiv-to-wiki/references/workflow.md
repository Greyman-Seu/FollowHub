# arxiv-to-wiki Workflow Notes

## Minimal Flow

For one new paper:

```text
arxiv URL / ID
-> paper-analyze
-> llm-wiki
-> validate wiki and source completeness
-> build and validate the wiki package
-> publish the package to R2
-> refresh website-facing data
-> verify source JSON and the public source page
```

Use this for most day-to-day knowledge-base growth. Publication is the persistent default and does not require a confirmation question.

## Preview Flow

When the user wants to inspect the note first:

```text
arxiv URL / ID
-> paper-analyze in draft mode
-> user review
-> llm-wiki
-> default publication flow after approval
```

## Existing Note Flow

When a source note already exists in `wiki/sources`:

```text
existing source note
-> llm-wiki attach-style integration
-> optional update-wiki
-> default publication and verification flow
```

## Structure Maintenance Flow

When multiple papers have accumulated around the same route:

```text
several source notes
-> update-wiki
```

Use this to create or refresh:

- `wiki/topics/*.md`
- `wiki/synthesis/*.md`
- `index.md`
- `purpose.md`

## Default Publication Flow

After every direct or attach run, unless the user explicitly opts out:

```text
existing wiki content
-> validate wiki
-> build FollowHub wiki package
-> run package completeness check
-> sync package to R2
-> publish-wiki / refresh website-facing data
-> verify manifest URL
-> verify source/<slug>.json
-> verify /wiki/source/<slug>
```

This happens after note authoring or structural maintenance, never before. Explicit opt-outs include `不发布`, `仅写入本地`, `只做草稿`, `不要同步网站/R2`, and equivalent instructions. Do not infer an opt-out from the absence of the word “发布”.

## Completeness-Checked Flow

For a normal write:

```text
arxiv URL / ID
-> paper-analyze writes wiki/sources/<slug>.md
-> run check_source_completeness.py --wiki-root ... --slug <slug>
-> fix source note if needed
-> rerun until no errors
-> llm-wiki structure integration
```

For the default website and R2 publication:

```text
existing wiki content
-> build FollowHub wiki package
-> run check_source_completeness.py --wiki-root ... --package-dir ... --slug <slug>
-> fix source note and rebuild package if JSON fields are missing
-> publish-wiki / R2 sync
-> verify package and public URLs
```

Treat missing structured background/method fields (`backgroundMotivation`, `backgroundGap`, `methodOverview`, `methodCore`, `methodBreakdown`, `methodTakeaways`) or risk fields (`riskLimitations`, `riskScenarios`, `riskJudgment`) in package JSON as a blocking error. The Markdown may look complete while the page-facing JSON is empty, so always check both layers before finishing.

If the source note contains a useful figure, require an explicit `hero_image` in Markdown and a non-empty `heroImage` in package JSON. The page does not infer its hero from `images` or `figureGallery`.

New notes must use the canonical bold labels from `arxiv-to-wiki/SKILL.md`. Heading-style blocks such as `### 方法概述` remain readable for legacy notes, but generators must not emit them or mix the two styles.

## Batch Flow With Subagents

When several arXiv papers are requested together and subagents are available:

```text
main agent: deduplicate paper list and assign one paper per worker
worker N: arxiv-to-wiki -> paper-analyze for exactly one paper
worker N: returns source slug/path and any uncertainty
main agent: runs completeness checks for every slug
main agent: updates topics/synthesis/index/log once
main agent: builds package, runs package completeness checks, then publishes and verifies unless the user explicitly opted out
```

Workers must not edit shared topic, synthesis, index, log, package, or website files unless explicitly assigned by the main agent.
