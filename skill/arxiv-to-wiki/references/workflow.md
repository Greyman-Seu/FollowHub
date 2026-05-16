# arxiv-to-wiki Workflow Notes

## Minimal Flow

For one new paper:

```text
arxiv URL / ID
-> paper-analyze
-> llm-wiki
```

Use this for most day-to-day knowledge-base growth.

## Preview Flow

When the user wants to inspect the note first:

```text
arxiv URL / ID
-> paper-analyze in draft mode
-> user review
-> llm-wiki
```

## Existing Note Flow

When a source note already exists in `wiki/sources`:

```text
existing source note
-> llm-wiki attach-style integration
-> optional update-wiki
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

## Website Refresh Flow

When the user wants the public or website-facing wiki refreshed:

```text
existing wiki content
-> publish-wiki
```

This should typically happen after note authoring or structural maintenance, not before.

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

For website or R2 sync:

```text
existing wiki content
-> build FollowHub wiki package
-> run check_source_completeness.py --wiki-root ... --package-dir ... --slug <slug>
-> fix source note and rebuild package if JSON fields are missing
-> publish-wiki / R2 sync
```

Treat missing `riskScenarios` or `riskJudgment` in package JSON as a blocking error. The Markdown may look complete while the page-facing JSON is empty, so always check both layers before finishing.

## Batch Flow With Subagents

When several arXiv papers are requested together and subagents are available:

```text
main agent: deduplicate paper list and assign one paper per worker
worker N: arxiv-to-wiki -> paper-analyze for exactly one paper
worker N: returns source slug/path and any uncertainty
main agent: runs completeness checks for every slug
main agent: updates topics/synthesis/index/log once
main agent: builds package, runs package completeness checks, then publishes if requested
```

Workers must not edit shared topic, synthesis, index, log, package, or website files unless explicitly assigned by the main agent.
