---
name: rss-collect
description: Use when an agent needs raw RSS entries for daily collection before semantic filtering, especially for WeChat, X/Twitter, and other feed-based sources.
---

# rss-collect

Raw RSS acquisition skill.

## Role

`rss-collect` only fetches feed entries and writes raw normalized feed records.

It does:

- fetch configured RSS/Atom feeds
- normalize feed-level metadata such as `guid`, `title`, `link`, `published`
- track incremental state and deduplicate by stable source entry id
- emit one raw collection bundle per run

It does not:

- fetch full article bodies
- decide whether an item enters the daily digest
- write Chinese summaries
- publish Follow data

## Agent Tool Surface

```bash
python3 skill/rss-collect/rss_collect.py help
python3 skill/rss-collect/rss_collect.py collect --config followhub.yaml --output rss-collect-output/2026-05-12-raw.json
```

## Config Shape

For a few feeds, put them directly under `rss.sources`:

```yaml
rss:
  daily:
    lookback_days: 2
    max_items_per_source: 50

  sources:
    - name: test-wechat
      type: wechat
      feed_url: https://example.com/wechat.xml
      tags: ["robotics"]
```

For many feeds, keep them in a separate YAML file and reference it:

```yaml
rss:
  sources_file: rss_sources.yaml
```

or

```yaml
rss:
  source_files:
    - rss_sources_wechat.yaml
    - rss_sources_x.yaml
```

## Downstream

The next skill is `rss-normalize`.
