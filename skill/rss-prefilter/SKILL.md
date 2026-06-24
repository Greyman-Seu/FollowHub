---
name: rss-prefilter
description: Use when an agent needs a fast title/source-only screening pass before full RSS content filtering, deciding keep/drop/uncertain for batches of feed entries.
---

# rss-prefilter

Fast first-pass screening worker for RSS items.

## Role

`rss-prefilter` reviews a small batch of feed items and returns:

- `keep`
- `drop`
- `uncertain`

It is a worker skill. It does not spawn subagents by itself.

The input may include `recent_story_history` so the reviewer can tell whether a title is:

- a brand-new story
- an obvious repeat
- a possible followup to a recently seen story

The input may also include `history_hint` per entry. Use it as a compact cue:

- `seen_recently`
- `current_story_status`
- `last_seen_date`
- `latest_story_status`
- `history_source_overlap`
- `history_publish_count`
- `history_max_mention_count`

The input may also include:

- `reviewer_prompt`
- `reviewer_checklist`
- `decision_criteria`
- `reviewer_output_schema`

Treat those as the canonical review template for this stage.

Review rule of thumb:

- recent `repeat` usually means `drop`
- recent `followup` is usually `keep` or `uncertain`, not automatic `drop`
- if the same source keeps repeating the same story without new substance, bias toward `drop`
- for `source_type: "x"`, bias much more aggressively toward `drop`: keep only posts with a concrete model/product/paper/dataset/benchmark/release, a specific technical capability/result, or a non-obvious trend/market/risk viewpoint
- drop X institutional activity logs, conference attendance notes, opening-ceremony/panel recaps, recruitment/course/promotion, and public-value/vision statements when they only say “AI/trust/society” without a concrete technical or trend claim

## Output

Return only JSON:

```json
{
  "items": [
    {
      "id": "wechat:entry-1",
      "decision": "keep",
      "reason": "标题直接命中主线。"
    }
  ]
}
```
