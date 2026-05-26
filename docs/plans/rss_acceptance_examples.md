# RSS Daily Acceptance Examples

This note defines scenario-driven acceptance examples for the personal RSS daily pipeline.

The target is daily push quality for subscribed WeChat / X / generic RSS sources.

Executable fixtures now live under:

- `skill/rss-daily/tests/fixtures/`

Current fixture-backed coverage includes:

- same WeChat article mirrored across feeds
- distinct canonical items grouped as same-story followup
- recent history hint generation for review inputs

## Example 1: Same Feed Repeats the Same Entry Twice

Input:

- same source feed
- same link
- same title
- same day

Expected:

- one `canonical_id`
- one `story_id`
- `story_status: repeat` for the duplicate case if duplicate-level status is surfaced, otherwise representative story remains `new`
- only one top-level digest story

## Example 2: Two Feeds Mirror the Same WeChat Article

Input:

- two different RSS feeds
- same `mp.weixin.qq.com/s?...` article
- one link may include tracking params

Expected:

- same `canonical_id`, derived from stable WeChat article identifiers
- same `story_id`
- `mention_count` reflects both mirrors
- one top-level digest story
- `related_items` preserves source traceability

## Example 3: One X Post Appears Through Multiple RSS Mirrors

Input:

- two RSS mirrors pointing to the same X/Twitter status URL
- different feed names

Expected:

- same `canonical_id`, based on status id
- same `story_id`
- one digest story
- multiple sources recorded under `source_names`

## Example 4: Day 1 Original Announcement, Day 2 WeChat Recap

Input:

- day 1: X or official RSS announcement
- day 2: WeChat recap article about the same event

Expected:

- different `canonical_id` values
- same `story_id` after story grouping if the recap is clearly about the same release
- day 1 item is `new`
- day 2 item should be eligible for `followup` if it adds useful context
- digest policy may include day 2 followup, but must not treat it as a brand-new unrelated story

## Example 5: X First, WeChat Second-Day Interpretation

Input:

- day 1: short X post with initial signal
- day 2: longer WeChat article with interpretation

Expected:

- different `canonical_id` values
- same `story_id` if the second-day writeup is clearly anchored to the original event
- `story_status` on the second-day item should prefer `followup` over `new`
- digest should keep only the higher-signal story card for the day, not two unrelated cards
- auto-filter should not drop the day-2 item solely because the same `story_id` appeared yesterday

## Example 6: Ad-Like WeChat Course Promo

Input:

- WeChat post with course / signup / promotion language
- no strong match to configured interest topics

Expected:

- may still receive a `canonical_id` and `story_id`
- should be dropped in `rss-prefilter` or `rss-filter`
- must not appear in final digest

## Example 7: Off-Topic but Legitimate News

Input:

- real article from subscribed source
- not ad-like
- does not match configured interest scope

Expected:

- collect, normalize, dedupe, and cluster still run normally
- filter decision should exclude it from digest
- exclusion reason should remain traceable

## Example 8: Same-Day Mixed Coverage of One Release

Input:

- one official release note
- one X discussion thread
- one WeChat summary post
- all point to the same release day

Expected:

- official release may have its own `canonical_id`
- commentary items may have different `canonical_id`
- all three may converge to one `story_id`
- digest should show one story card with:
  - representative item
  - merged `source_types`
  - merged `source_names`
  - accurate `mention_count`

## Operational Rule

The acceptance target is not “perfect semantic merging”.

The acceptance target is:

- obvious same-content duplicates collapse deterministically
- obvious same-story coverage does not spam the daily digest
- the final daily push preserves enough traceability to debug bad merges or bad exclusions
