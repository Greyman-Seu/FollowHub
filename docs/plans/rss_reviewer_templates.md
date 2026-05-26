# RSS Reviewer Templates

This note defines reusable reviewer templates for personal RSS daily use.

The point is to keep daily judgment stable:

- what counts as worth reading
- what counts as obvious repeat noise
- what counts as a meaningful followup

## Prefilter Template

Use at the title/source-only stage.

Prompt:

```text
Review this RSS item using title/source-level signals first.
Use recent story history to decide whether it looks like a new story, a repeat, or a meaningful followup.
Prefer drop for obvious repeat coverage, keep for clear in-scope new items, and uncertain for borderline followups.
```

Checklist:

1. Does the title/source clearly match the configured interest scope?
2. Does recent history suggest this is just a repeat of a recently pushed story?
3. If it is a followup, is there enough signal to keep it for deeper review?
4. Is the item likely ad-like, promotional, or otherwise low-signal?

Default decision bias:

- `keep`: clear in-scope new item
- `drop`: obvious repeat, ad, or off-topic item
- `uncertain`: possible followup or weak match that needs content review

## Filter Template

Use at the final semantic inclusion stage.

Prompt:

```text
Review this RSS item for final daily digest inclusion.
Use content, recent story history, and history_hint together.
Exclude obvious repeats, include strong in-scope new items, and include followups only when they add signal beyond prior coverage.
```

Checklist:

1. Does the item add meaningful signal for today's digest?
2. Is it a repeat of a recently pushed story without new substance?
3. If marked followup, does it materially advance the prior story?
4. Do source overlap, publish count, or prior mention count raise the inclusion bar?
5. Should the item be excluded even if it matches scope because it is low-signal or repetitive?

Default inclusion bias:

- include strong new items
- exclude obvious repeats
- include followups only when they make you more informed than yesterday

## Personal Rule

For personal use, the right failure mode is:

- miss a few borderline items
- do not flood the daily push with repeats

The system should optimize for trust and skim quality, not maximum recall.
