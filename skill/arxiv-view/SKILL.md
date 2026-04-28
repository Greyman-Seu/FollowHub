---
name: arxiv-view
description: Use when the user wants a static HTML viewer for arXiv daily briefs, backfills, or search results produced by arxiv-find, including local favorites and clipboard export of selected arXiv IDs.
---

# arxiv-view

Render `arxiv-find` outputs into a static directory bundle for browser-based review.

## Requirements Snapshot

- Consume `arxiv-find` outputs only.
- Support `daily`, `backfill`, and `search`.
- Produce a static directory, not a live service.
- Store favorites in browser `localStorage`.
- Copy favorite arXiv IDs to the clipboard.
- Keep retrieval and rendering separate.

## Design Pattern

`arxiv-view` is render-only:

1. Load one `arxiv-find` output file.
2. Normalize it into a unified view model.
3. Write a static directory bundle:
   - `index.html`
   - `app.js`
   - `styles.css`
   - `data.json`
4. Let the browser handle filtering and favorites locally.

## Input Contract

Accepted inputs:

- one `daily` JSON output from `arxiv-find`
- one `search` JSON output from `arxiv-find`
- one `backfill` overview markdown file from `arxiv-find`, plus its linked daily artifacts

`arxiv-view` does not run retrieval itself and does not read profile YAML files.

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-view/arxiv_view.py help
python3 /home/tenstep/workspace/followhub/skill/arxiv-view/arxiv_view.py build --input /path/to/daily.json --output-dir ./arxiv-view-out
python3 /home/tenstep/workspace/followhub/skill/arxiv-view/arxiv_view.py build --input /path/to/backfill-overview.md --output-dir ./arxiv-view-out
```

## Output

The generated directory contains:

- `index.html`
- `app.js`
- `styles.css`
- `data.json`

Open `index.html` in a browser or publish the directory as a static site later.

## Interaction Model

- free-text filtering
- category filter
- source-day filter when available
- favorites-only toggle
- local favorites
- clipboard export of favorite arXiv IDs

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Pointing arxiv-view at a profile YAML | Give it an `arxiv-find` result instead |
| Expecting server-side storage | Favorites are browser-local in phase 1 |
| Mixing retrieval into view | Keep `arxiv-find` and `arxiv-view` separate |
