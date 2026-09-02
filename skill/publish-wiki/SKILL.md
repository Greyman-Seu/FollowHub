---
name: publish-wiki
description: Use when FollowHub needs to publish analyzed wiki source notes as online-readable Page routes, including data sync, validation, page_github commit/push, deployment wait, and public URL verification.
---

# publish-wiki

Run the final part of the FollowHub paper workflow and leave the result readable on the public Page site:

```text
paper-analyze -> llm-wiki/wiki/sources -> wiki-sync-page -> page_github/main -> online Page URL
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

4. Publish the generated wiki data to R2.
5. Commit `src/data/generated/wiki-sync` in `page_github` and push `main`.
6. Wait for the deployment and verify the public URL returns HTTP 200.
7. Report:

- which generated files were updated
- whether type-check passed
- the verified online Page URL

For a single source, pass its slug so the exact online paper-reading page is verified:

```bash
python3 skill/publish-wiki/publish_wiki.py \
  --wiki-root <wiki_root> \
  --page-root <page_root> \
  --config <followhub_config> \
  --verify-slug <source-slug>
```

The default public route is:

```text
https://tenstep.top/wiki/source/<source-slug>
```

`--no-page-push` and `--no-page-verify` are diagnostics/testing escape hatches only. Do not use them for a normal user request to publish a Page.

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
- `page_github/main` contains the generated source data
- the exact public source URL returns HTTP 200

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Running before the note exists | Make sure `paper-analyze` has already written `wiki/sources/*.md` |
| Treating publish-wiki as note authoring | Keep authoring in `paper-analyze` |
| Updating the website without validation | Always run `astro check` after sync |
| Stopping after local generated data exists | Commit and push `page_github/main`, then verify the online source URL |
| Returning an R2 JSON/HTML URL when the user asked for Page | Return `https://tenstep.top/wiki/source/<slug>` after it is reachable |
