---
name: arxiv-collect
description: Use when an agent needs raw arXiv daily or backfill data before any semantic filtering, especially category-wide New submissions for the FollowHub arXiv pipeline.
---

# arxiv-collect

Raw arXiv acquisition skill.

## Role

`arxiv-collect` only collects and normalizes raw arXiv papers.

It does:

- daily collection from `arxiv.org/list/<category>/new`
- backfill collection from the arXiv export API with submitted-date windows
- de-duplication across configured categories
- daily metadata hydration from `arxiv.org/abs/<arxiv_id>` pages, following the `ref/ArxivReader` approach

It does not:

- decide whether a paper enters Follow
- classify papers into Follow domains
- write Chinese summaries
- publish to R2

## Daily Semantics

Daily should be close to `ref/ArxivReader`:

- read configured categories such as `cs.RO`, `cs.AI`, and `cs.LG`
- parse the official `New submissions` section
- use the arXiv page `listing_date` as the source date when it differs from the local calendar date
- hydrate title, authors, abstract, subjects, and PDF URL from `arxiv.org/abs/<arxiv_id>`
- keep the full category raw set
- attach lightweight hints only as metadata

Daily should not depend on `export.arxiv.org/api/query?id_list=...` for metadata. The export API can return `429` under bursty daily runs; use abs-page hydration first and list-page parsing as the fallback.

Keywords, excludes, and topic context are hints for downstream review. They are not final filters.

## Backfill Semantics

Backfill uses the arXiv export API:

```text
(cat:cs.RO OR cat:cs.AI OR cat:cs.LG) AND submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]
```

It runs one date at a time and emits one daily result per date.

## Agent Tool Surface

```bash
python3 skill/arxiv-collect/arxiv_collect.py help
python3 skill/arxiv-collect/arxiv_collect.py validate-profile --profile followhub.yaml
python3 skill/arxiv-collect/arxiv_collect.py run --mode daily --profile followhub.yaml
python3 skill/arxiv-collect/arxiv_collect.py run --mode backfill --profile followhub.yaml --from-date 2026-05-01 --to-date 2026-05-03
```

## Downstream

The next skill in the pipeline is `arxiv-filter`.

`arxiv-filter` or its subagent workers decide:

- `include_in_follow`
- `domains`
- `one_liner_zh`
- `summary_cn`
- `reason`
