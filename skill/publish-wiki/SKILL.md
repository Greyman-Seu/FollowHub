---
name: publish-wiki
description: Use when FollowHub needs a single workflow to move from analyzed wiki source notes to refreshed website data and publish-ready wiki pages, including sync and validation steps.
---

# publish-wiki

Run the final part of the FollowHub paper workflow:

```text
paper-analyze -> llm-wiki/wiki/sources -> wiki-sync-page -> page_github
```

This skill is not for writing new paper notes.  
It is for turning already-written wiki notes into refreshed website-facing data.

## One-Line Use

Typical user intent:

- `把刚分析的论文同步到网站`
- `更新 wiki 页面`
- `把 llm-wiki 的最新论文刷到站点`

## When To Use

Use this skill when:

- one or more new source notes have already been written into `llm-wiki/wiki/sources`
- the user says “同步网站”, “发布 wiki”, “更新站点”, “把 wiki 内容刷到页面”
- the user wants the website layer refreshed after recent note updates

## Role Split

- `paper-analyze`
  - writes the structured source note
- `update-wiki`
  - decides whether sources should become topics or synthesis notes
- `wiki-sync-page`
  - parses wiki notes and writes generated website data
- `publish-wiki`
  - orchestrates the sync + validation path

## Workflow

1. Confirm the target wiki root and page repo root
2. Run:

```bash
python3 skill/wiki-sync-page/wiki_sync_page.py sync --wiki-root <wiki_root> --page-root <page_root>
```

3. Validate the website repo still type-checks:

```bash
pnpm -C <page_root> exec astro check
```

4. Report:

- which generated files were updated
- whether type-check passed
- whether the site is ready for deployment

## Recommended End-to-End Flow

For one new paper:

1. `paper-analyze`
2. optional `md-preview`
3. `publish-wiki`

For periodic structure maintenance:

1. `update-wiki`
2. `publish-wiki`

## Success Criteria

A successful run should leave the repo in a state where:

- `src/data/generated/wiki-sync/sources.json` reflects the latest notes
- `/wiki/source/[slug]` can render those notes
- Astro type-check passes

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Running before the note exists | Make sure `paper-analyze` has already written `wiki/sources/*.md` |
| Treating publish-wiki as note authoring | Keep authoring in `paper-analyze` |
| Updating the website without validation | Always run `astro check` after sync |
