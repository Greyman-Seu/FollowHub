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
- collect many feeds concurrently inside one process using worker threads
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
python3 skill/rss-collect/rss_collect.py prune-stale --source-file rss_sources_x_nitter.yaml --config followhub.yaml --apply
```

`prune-stale` is for maintaining large source lists.

Recommended rule:

- remove a source if its latest feed item is older than 183 days
- remove a source if the feed returns 404 / empty XML / parse failure
- run without `--apply` first if you only want the report

## Config Shape

For a few feeds, put them directly under `rss.sources`:

```yaml
rss:
  daily:
    lookback_days: 2
    max_items_per_source: 50

  collect:
    max_workers: 8
    request_timeout_seconds: 30

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

## Proxy / VPN

For Nitter / X / XCancel style feeds, try direct terminal access first.
Only add proxy settings if collection shows real DNS / timeout /
connection-refused failures.

Recommended config:

```yaml
rss:
  proxy:
    http: http://127.0.0.1:7890
    https: http://127.0.0.1:7890
```

Or use shell env:

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

Agent rule:

- if feed collection fails with DNS / timeout / connection-refused errors and no proxy is configured, ask the user for the proxy/VPN setup
- if a proxy is configured but still fails, ask the user to confirm the proxy host/port before retrying many feeds

## Concurrency Recommendation

Use in-process concurrent collection for RSS feeds.

- Preferred: thread-based concurrency in `rss-collect`
- Not preferred: spawning subagents per feed

Reason:

- feed fetching is network I/O bound, not model-reasoning bound
- one process with worker threads is cheaper, easier to observe, and easier to retry
- keep subagents for judgment-heavy stages like `rss-prefilter`, `rss-filter`, or summary writing

## Downstream

The next skill is `rss-normalize`.
