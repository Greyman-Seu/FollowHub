---
name: wiki-sync-page
description: Use when public content from llm-wiki should be mapped into the website wiki layer, including source, topic, synthesis, and graph artifacts, without re-analyzing the underlying papers.
---

# wiki-sync-page

Sync public `llm-wiki` content into the website `/wiki` layer.

## Requirements Snapshot

- Treat `llm-wiki` as the source of truth.
- Read only public-ready content.
- Map source, topic, synthesis, and graph artifacts into the website data layer.
- Do not re-summarize papers.
- Do not mutate the analysis content unless normalization is required for the website contract.

## Role Split

- `paper-analyze`
  - creates the wiki source note
- `wiki-sync-page`
  - publishes wiki content into the site
- website `/wiki`
  - renders synchronized public knowledge

## Expected Inputs

- configured `llm-wiki` root
- configured website repo root
- one or more public wiki entries

Expected wiki areas:

- `wiki/sources/`
- `wiki/topics/`
- `wiki/synthesis/`
- graph artifacts such as `knowledge-graph.html` and related assets

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/wiki-sync-page/wiki_sync_page.py inspect --wiki-root /path/to/llm-wiki --page-root /path/to/site
python3 /home/tenstep/workspace/followhub/skill/wiki-sync-page/wiki_sync_page.py sync --wiki-root /path/to/llm-wiki --page-root /path/to/site
```

## Sync Targets

At minimum this skill should maintain:

- website wiki source data
- website wiki topic data
- website wiki synthesis data
- website graph artifact location

## Workflow

1. Discover the configured `llm-wiki` root.
2. Read public-ready source, topic, and synthesis entries.
3. Normalize fields into the website contract.
4. Copy or transform graph artifacts into the website static path.
5. Write the synced output into the site repo.
6. Report exactly what changed.

## Notes

- This skill is publish-oriented, not analysis-oriented.
- If a wiki note is draft-only or private, skip it.
- If a field is missing for website rendering, report it instead of inventing content.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Re-analyzing papers during sync | Treat wiki notes as the source of truth |
| Publishing draft or private notes | Sync only public-ready entries |
| Mixing preview behavior into sync | Keep preview in `md-preview` |
