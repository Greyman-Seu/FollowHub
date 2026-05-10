---
name: md-preview
description: Use when the user wants a local Markdown file rendered into temporary HTML and served on a local preview URL for quick review before publishing or syncing.
---

# md-preview

Render one Markdown file into temporary HTML and serve it locally.

## Requirements Snapshot

- Accept one local Markdown path.
- Generate one temporary HTML file.
- Start a local HTTP server for preview.
- Return the local preview URL and the generated file path.
- Do not modify the original Markdown file.

## Input Contract

Accepted input:

- one absolute or repo-relative path to a Markdown file

Optional inputs:

- output directory override
- port override
- title override

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/md-preview/scripts/md_preview.py render --input /path/to/file.md
python3 /home/tenstep/workspace/followhub/skill/md-preview/scripts/md_preview.py serve --input /path/to/file.md --port 8766
```

## Workflow

1. Resolve the Markdown file path.
2. Render the Markdown into temporary HTML.
3. Write the HTML into a temporary preview directory.
4. Start a local HTTP server for preview.
5. Return:
   - rendered HTML path
   - preview directory
   - local preview URL

## Notes

- This is for local preview only.
- It is intentionally separate from `paper-analyze`.
- It is also separate from `wiki-sync-page`; preview is not publish.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Expecting this skill to write wiki content | Use `paper-analyze` for that |
| Expecting this skill to update the website | Use `wiki-sync-page` later |
| Giving it a directory instead of a file | Pass one Markdown file path |

