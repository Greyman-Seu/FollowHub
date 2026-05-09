# arXiv Daily Ops

## Goal

Define the current production path for arXiv daily and backfill.

The production chain is:

```text
arxiv-daily
  -> arxiv-collect
  -> title-prefilter
  -> arxiv-filter
  -> arxiv-enrich
  -> follow-publish
  -> rcli
```

`arxiv-daily` is a prompt-only pipeline skill. It does not own a Python CLI.

## Daily

Daily means today's category-wide `New submissions`.

Flow:

1. Use `arxiv-collect` to collect raw daily papers.
2. If `listing_date != today`, default behavior is to stop before publish because arXiv `new` has not rolled over yet.
3. Build title-prefilter tasks from the raw daily JSON.
4. Use title-prefilter subagents to produce `keep / drop / uncertain`.
5. Build full filter tasks from `keep + uncertain`.
6. Use `arxiv-filter` subagents to decide `include_in_follow`, `domains`, `one_liner_zh`, `summary_cn`, and `reason`.
7. If a selected paper still lacks `one_liner_zh` or `summary_cn`, retry `arxiv-filter` for that paper first.
8. Enrich only selected papers with `arxiv-enrich`.
9. Merge filter and enrich outputs into a Follow daily digest.
10. Publish with `follow-publish`.
11. Verify R2/page JSON with `rcli` or public URLs.

Raw daily should be comparable to `ArxivReader` category daily semantics. For `cs.RO`, `cs.AI`, and `cs.LG`, this may be more than 100 papers.

## Backfill

Backfill means missed daily raw collection for historical dates.

Flow:

1. Use `arxiv-collect` backfill for each target date.
2. Keep one raw daily JSON per date.
3. Run `arxiv-filter` per date.
4. Enrich selected papers per date.
5. Publish one digest per date.

Historical publish must be explicit through `follow-publish` safety flags.

## Search

Search is not part of the production daily/backfill path.

If needed later, create a separate `arxiv-search` skill with its own semantics.

## Validation

Validate in layers:

- Collection:
  - date is correct
  - source is `list-new` for daily
  - `listing_date` should match the intended publish date for a true same-day run
  - raw count is category-wide
  - configured categories are present
- Filter:
  - title-prefilter should only remove obviously irrelevant papers
  - uncertain papers must continue to full filter
  - every raw item has an include/exclude decision
  - selected papers match the user's focus
  - excluded papers have clear reasons
- Enrich:
  - selected papers have authors, links, abstract, and score fields
  - Chinese summaries come from `arxiv-filter`, not static rules
  - `arxiv-enrich` is not the owner of Chinese summary generation
- Publish gating:
  - if Chinese summary fields are missing, retry `arxiv-filter` rather than silently degrading
  - if retry still fails, the paper may remain visible on page as an incomplete follow item
- Publish:
  - `follow/latest.json`
  - `follow/daily/YYYY-MM-DD.json`
  - `follow/sources/arxiv.json`
  - `/follow/arxiv`

## Suggested Entry Phrases

```text
/arxiv-daily 帮我统计今天信息
```

```text
/arxiv-daily 帮我补 2026-05-01 到 2026-05-03 的更新
```
