---
name: rss-filter
description: Use when an agent or subagent needs to semantically filter RSS items for FollowHub, deciding digest inclusion, domains, one-line Chinese summaries, Chinese abstracts, and review reasons.
---

# rss-filter

Semantic review worker for RSS items.

## Role

`rss-filter` reviews a small batch of normalized or fetched RSS items and returns structured inclusion results.

It is a worker skill. It does not spawn subagents by itself.

The input may include `recent_story_history` so the reviewer can judge:

- whether the item is just repeating a recently pushed story
- whether it is a meaningful followup worth pushing today
- whether prior source coverage changes digest priority

The input may also include `history_hint` per entry. Use it to make the inclusion decision more consistent:

- `seen_recently`
- `current_story_status`
- `last_seen_date`
- `latest_story_status`
- `history_source_overlap`
- `history_publish_count`
- `history_max_mention_count`
- `history_latest_title`

The input may also include:

- `reviewer_prompt`
- `reviewer_checklist`
- `decision_criteria`
- `reviewer_output_schema`

Treat those as the canonical review template for this stage.

Review rule of thumb:

- recent `repeat` should usually be excluded
- recent `followup` should be included only when it adds signal beyond prior coverage
- high prior `publish_count` or `max_mention_count` should raise the bar for inclusion unless the new item clearly advances the story
- for `source_type: "x"`, use a high-signal bar: include only if the post contains a concrete object and value, such as a model/product/paper/dataset/benchmark/release, a specific capability/result/comparison, or a substantive technical/trend/market/risk viewpoint
- exclude X posts that are only institutional PR or activity logs: conference attendance, opening ceremonies, panels, “shared our vision”, “AI/trust/society” principles, mission/commitment statements, hiring/course/promotion, or generic event recaps
- if the best one-line summary would be “提到 AI/模型/Agent 相关动态；需要补全具体对象、观点或能力变化”, exclude it instead of publishing a placeholder

For excluded X items, leave `one_liner_zh` and `summary_cn` empty unless a short exclusion note is useful in `reason`.

## Output

Return only JSON:

```json
{
  "items": [
    {
      "id": "wechat:entry-1",
      "include_in_digest": true,
      "domains": [
        {"slug": "agent", "name": "Agent"}
      ],
      "one_liner_zh": "一句话说明核心信息。",
      "summary_cn": "正文内容的忠实中文摘要。",
      "reason": "纳入或排除原因。"
    }
  ]
}
```
