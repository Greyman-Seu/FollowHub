# RSS Artifact Contract

This note freezes the artifact handoff contract for the personal RSS daily pipeline.

The pipeline target is daily push for subscribed WeChat / X / generic RSS sources, using a story-first digest model.

## Stage Order

1. `rss-collect`
2. `rss-normalize`
3. `rss-fetch`
4. `rss-dedupe`
5. `rss-cluster`
6. recent story history build
7. `rss-prefilter`
8. `rss-filter`
9. `rss-enrich`
10. `rss-digest`
11. `rss-publish`
12. `rss-verify`

## Contract Rules

- `rss-normalize` is deterministic.
- `canonical_id` starts in `rss-dedupe`.
- `story_id` and `story_status` start in `rss-cluster`.
- `rss-publish` must package digest output only.
- `rss-publish` must not recompute `canonical_id`, `story_id`, or `story_status`.

## 1. Normalized Item

Produced by: `rss-normalize`

Required fields:

- `id`
- `source_name`
- `source_type`
- `title`
- `url`
- `published_at`

Recommended fields:

- `normalized_url`
- `origin_url`
- `origin_host`
- `author`
- `summary`
- `tags`
- `raw_meta`

Forbidden at this stage:

- `canonical_id`
- `story_id`
- `story_status`

Example:

```json
{
  "id": "wechat:feed-a:entry-001",
  "source_name": "feed-a",
  "source_type": "wechat",
  "title": "Robot policy update",
  "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz",
  "normalized_url": "https://mp.weixin.qq.com/s?__biz=abc&idx=1&mid=123&sn=xyz",
  "origin_url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz",
  "origin_host": "mp.weixin.qq.com",
  "author": "",
  "published_at": "2026-05-17T09:00:00Z",
  "summary": "Short feed summary",
  "tags": ["robot"],
  "raw_meta": {
    "guid": "feed-a-entry-001"
  }
}
```

## 2. Deduped Item

Produced by: `rss-dedupe`

Required fields:

- all normalized item fields needed downstream
- `canonical_id`
- `dedupe_match_kind`
- `duplicate_count`
- `duplicate_items`

Rules:

- same-content duplicates collapse to one representative record
- representative selection is deterministic
- `duplicate_items` preserves traceability
- this stage does not decide same-story grouping

Example:

```json
{
  "id": "feed-b:entry-002",
  "source_name": "feed-b",
  "source_type": "wechat",
  "title": "Robot policy update",
  "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz&utm_source=rss",
  "normalized_url": "https://mp.weixin.qq.com/s?__biz=abc&idx=1&mid=123&sn=xyz",
  "origin_url": "https://mp.weixin.qq.com/s?__biz=abc&idx=1&mid=123&sn=xyz",
  "published_at": "2026-05-17T10:00:00Z",
  "canonical_id": "wechat:abc:123:1:xyz",
  "dedupe_match_kind": "url",
  "duplicate_count": 1,
  "duplicate_items": [
    {
      "id": "feed-a:entry-001",
      "source_name": "feed-a",
      "source_type": "wechat",
      "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz",
      "published_at": "2026-05-17T09:00:00Z"
    }
  ]
}
```

## 3. Clustered Item

Produced by: `rss-cluster`

Required fields:

- all deduped item fields needed downstream
- `story_id`
- `story_status`
- `story_match_confidence`

Optional fields:

- `story_tokens`

Rules:

- `story_id` groups same-story records
- `story_status` must be one of:
  - `new`
  - `followup`
  - `repeat`
- `repeat` is for same-content mirrors or duplicate-heavy records
- `followup` is for later same-story coverage with a different `canonical_id`
- this stage may emit agent handoff tasks for ambiguous merges

Example:

```json
{
  "id": "feed-b:entry-002",
  "source_type": "wechat",
  "source_name": "feed-b",
  "title": "Robot policy update",
  "published_at": "2026-05-17T10:00:00Z",
  "canonical_id": "wechat:abc:123:1:xyz",
  "duplicate_count": 1,
  "story_id": "story:wechat:abc:123:1:xyz",
  "story_status": "new",
  "story_match_confidence": "high",
  "story_tokens": ["robot", "policy", "update"]
}
```

## 4. Filter Result Item

Produced by: `rss-filter`

Required fields:

- `id`
- `include_in_digest`
- `reason`

Recommended fields:

- `domains`
- `one_liner_zh`
- `summary_cn`

Rules:

- `rss-filter` decides whether an item should be included in the digest
- it does not create or modify `canonical_id`
- it does not create or modify `story_id`

Example:

```json
{
  "id": "feed-b:entry-002",
  "include_in_digest": true,
  "domains": [
    {
      "slug": "physical-embodied-intelligence",
      "name": "Physical/Embodied Intelligence"
    }
  ],
  "one_liner_zh": "机器人策略更新，集中在操作 policy 改进。",
  "summary_cn": "文章介绍了一项机器人操作策略更新，重点在训练和泛化表现。",
  "reason": "直接命中机器人策略主线。"
}
```

## 5. Enriched Item

Produced by: `rss-enrich`

Required fields:

- clustered item fields required downstream
- filter decision fields required downstream
- stable display fields for digest packaging

Required digest-facing fields:

- `id`
- `story_id`
- `story_status`
- `source_name`
- `source_type`
- `title`
- `url`
- `published_at`
- `canonical_id`
- `duplicate_count`
- `duplicate_items`
- `domains`
- `one_liner_zh`
- `summary_cn`
- `include_in_digest`

Rules:

- preserve existing Chinese fields if already present
- emit agent completion tasks when Chinese fields are missing
- do not silently drop story fields

## 6. Story-Oriented Digest Item

Produced by: `rss-digest`

The digest is story-first. One top-level digest card represents one story.

Required story fields:

- `story_id`
- `story_status`
- `representative_item_id`
- `title`
- `summary`
- `one_liner_zh`
- `summary_cn`
- `first_seen_at`
- `last_seen_at`
- `source_types`
- `source_names`
- `mention_count`
- `related_items`

Compatibility fields allowed during transition:

- `id`
- `source_type`
- `source_name`
- `url`
- `published_at`
- `canonical_id`

Rules:

- top-level digest cards must not duplicate same-day same-story items
- `mention_count` includes grouped items and same-content duplicates
- `related_items` keeps per-item traceability for debugging

Example:

```json
{
  "story_id": "story:wechat:abc:123:1:xyz",
  "story_status": "new",
  "representative_item_id": "feed-b:entry-002",
  "title": "Robot policy update",
  "summary": "机器人策略更新，集中在操作 policy 改进。",
  "one_liner_zh": "机器人策略更新，集中在操作 policy 改进。",
  "summary_cn": "文章介绍了一项机器人操作策略更新，重点在训练和泛化表现。",
  "first_seen_at": "2026-05-17T09:00:00Z",
  "last_seen_at": "2026-05-17T10:00:00Z",
  "source_types": ["wechat"],
  "source_names": ["feed-a", "feed-b"],
  "mention_count": 2,
  "related_items": [
    {
      "id": "feed-a:entry-001",
      "source_name": "feed-a",
      "source_type": "wechat",
      "published_at": "2026-05-17T09:00:00Z",
      "url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz"
    }
  ]
}
```

## 7. Story Ledger

Produced by: `rss-daily` orchestration after a successful daily digest

Purpose:

- persist cross-day story state across all daily runs
- accumulate history beyond the recent digest lookback window
- provide a stable state layer for future filtering and review

Default path:

- `rss-daily-output/_state/story-ledger.json`

Required fields:

- `updated_at`
- `story_count`
- `stories`

Each ledger row should support:

- `story_id`
- `first_seen_date`
- `seen_dates`
- `last_seen_date`
- `latest_story_status`
- `latest_title`
- `source_types`
- `source_names`
- `max_mention_count`
- `publish_count`

## 8. Story History

Produced by: `rss-daily` orchestration before filter

Purpose:

- aggregate recent digest story history across previous daily runs
- merge it with persistent ledger state
- support cross-day auto-filter decisions
- avoid relying only on the immediately previous day

Required fields:

- `run_date`
- `lookback_days`
- `story_count`
- `stories`

Each story history row should support:

- `story_id`
- `seen_dates`
- `last_seen_date`
- `latest_story_status`
- `latest_title`

Default policy:

- read recent daily digests from the previous 7 days unless config overrides it

## 9. Digest Envelope

Produced by: `rss-digest`, consumed by `rss-publish`

Required top-level fields:

- `summary`
- `highlights`
- `counts`
- `stories`

Compatibility fields allowed during transition:

- `sections`

Rules:

- `stories` is the canonical top-level story list
- `sections` may remain temporarily for page compatibility
- new code should prefer `stories`

Example:

```json
{
  "summary": "Selected 3 RSS stories for today.",
  "highlights": [
    "机器人策略更新，集中在操作 policy 改进。"
  ],
  "counts": {
    "wechat": 1,
    "x": 1,
    "rss": 1
  },
  "stories": [],
  "sections": []
}
```
