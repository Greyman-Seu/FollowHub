---
name: rss-daily
description: Use when the user asks for today's RSS follow-up or a missed-day RSS backfill; this skill is an agent-native workflow that must execute collect -> normalize -> fetch -> dedupe -> cluster -> prefilter -> filter -> enrich -> digest -> publish -> verify in order.
---

# rss-daily

Pipeline-level skill for RSS daily follow-up.

`rss-daily` owns orchestration. It must not replace required stages with a manual shortlist from raw feeds.

`rss-daily` is a workflow skill, not a CLI-first skill.

- The primary entrypoint is this `SKILL.md`.
- The invoking agent should read this file, gather repo/config context, and run the workflow directly.
- Helper scripts may exist for artifact validation, local replay, or full-pipeline smoke tests, but they are not the canonical user-facing entrypoint.
- The agent must not reinterpret missing worker outputs as permission to skip `rss-prefilter`, `rss-filter`, or Chinese-field completion.

## Non-Negotiable Execution Contract

For a normal daily run, the agent must execute these stages in order:

1. `rss-collect`
2. `rss-normalize`
3. `rss-fetch`
4. `rss-dedupe`
5. `rss-cluster`
6. `rss-prefilter`
7. `rss-filter`
8. `rss-enrich`
9. `rss-digest`
10. `rss-publish`
11. `rss-verify`

If any required step cannot be completed, the agent must stop and report the blocker instead of silently substituting a lower-quality path.

## Hard Prohibitions

The agent must not:

- manually shortlist raw RSS items as a substitute for `rss-prefilter` or `rss-filter`
- publish directly from `rss-collect` / `rss-normalize` / `rss-fetch` output
- skip `rss-filter` when the candidate set is non-trivial
- treat `rss-enrich`'s placeholder or empty Chinese fields as "good enough" for production publishing
- publish a digest while `one_liner_zh` / `summary_cn` are still missing unless the user explicitly accepts fallback-quality output
- confuse local helper-script success with a production-quality digest

## Skill Boundaries

- `rss-collect`
  - raw RSS/Atom acquisition
  - source fan-in, source file loading, proxy resolution
  - source maintenance helper via `prune-stale`
- `rss-normalize`
  - normalized canonical feed item structure
- `rss-fetch`
  - fetches or preserves article/page content
  - should improve body availability, not semantic judgment
- `rss-dedupe`
  - entry-level duplicate collapse
- `rss-cluster`
  - story-level grouping
  - story id / story status / mention counts
- `rss-prefilter`
  - fast early screening
  - title/source/history-level keep / drop / uncertain
- `rss-filter`
  - final include / exclude decision
  - owns domains and whether an item is worth today's digest
- `rss-enrich`
  - post-filter metadata completion
  - links, entities, Chinese summary fields, one-line summary fields
- `rss-digest`
  - convert enriched selected entries into final digest structure
- `rss-publish`
  - package digest into page-ready Follow JSON
- `rss-verify`
  - confirm required publish artifacts exist and are internally consistent

## Default Operating Modes

There are two legitimate operating modes:

1. Agent-reviewed production mode
   - preferred
   - `rss-prefilter`, `rss-filter`, and missing Chinese-field completion are performed by the invoking agent and/or subagents
   - this is the path for actual daily publishing

2. Helper-script test mode
   - acceptable only for smoke tests or pipeline debugging
   - uses `--auto-workers`
   - may auto-generate `prefilter_results.json`, `filter_results.json`, and fallback Chinese fields
   - proves the chain can run, but does not by itself prove publication quality

The invoking agent must distinguish these modes clearly when reporting success.

## X / Twitter Daily Path

For `x` items, the daily contract is stricter than WeChat:

- treat each post as its own candidate item; do not merge multiple same-day posts from the same account into one digest row
- use RSS as the acquisition layer only
- perform story grouping before filtering so retweets / repeats / quoted chains can be evaluated as clusters
- use agent or CLI worker stages for `prefilter` / `filter`; do not publish raw tweet text directly from collect/fetch
- final page-facing output should keep only:
  - account identity
  - original X link
  - one concise Chinese `one_liner_zh`
- do not expose long raw tweet text, English fallback snippets, or separate translation cards on the X source page unless the user explicitly asks for a verbose mode


## X / Twitter Summary Quality Gate

For X/Twitter items, low-information summaries are production blockers. X should be filtered more aggressively than WeChat: if a post does not contain a concrete technical/trend signal, drop it instead of trying to summarize it.

Do not publish generic lines such as:

- “分享了一条值得查看的动态”
- “转发并评论了一条值得关注的动态”
- “分享了一段演示或产品展示”
- “分享了一项研究进展”
- “发布了一项新功能或产品更新”

A production `one_liner_zh` must extract concrete information from the post or quoted/reposted item, preferably including at least one of:

- product / model / paper / project name
- concrete claim, capability, benchmark, result, release detail, pricing/cost/latency/throughput detail
- the author’s specific viewpoint or why the item matters

Drop instead of publish when an X item is only:

- conference attendance, opening ceremony, panel discussion, workshop, or institutional activity recap
- “shared our vision / mission / commitment” style public-relations language
- broad “AI, trust, society, responsible AI” statements without a technical or trend claim
- recruitment, course, event registration, sponsorship, or generic promotion
- social congratulations, photo/video-only posts, or “we were honored to join…” posts

Example that should be dropped: an institutional account says its CEO attended a panel about “AI era: technology, truth and trust” and restates a mission to build trustworthy AI, but gives no concrete product, model, research result, benchmark, policy detail, or trend argument.

Good examples:

- “MaineCoon 被称为首个不限时长的交互式音视频模型，展示了快速生成视频并走向实时视频聊天界面的可能性。”
- “Jeff Clune 转述研究称前沿 AI 在对话说服力上已超过专家人类，包括世界冠军辩手和职业游说者。”

If the pipeline cannot extract a concrete fact, the item must be sent to agent completion or dropped from production digest; do not fill it with a generic placeholder. For X specifically, prefer dropping over completion when the underlying post is just institutional activity/context with no technical or trend substance.

## Daily Procedure

1. Resolve config:
   - prefer `FOLLOWHUB_CONFIG`
   - otherwise use repo-local `followhub.yaml`
2. Run `rss-collect`.
3. Run `rss-normalize`.
4. Run `rss-fetch`.
   - direct terminal network access is preferred
   - only add proxy settings after real DNS / timeout / connection-refused failures
5. Run `rss-dedupe`.
6. Run `rss-cluster`.
7. Build `prefilter_input.json`.
8. Use subagents or equivalent worker delegation to produce `prefilter_results.json`.
9. Build `filter_input.json` from `keep` + `uncertain`.
10. Use subagents or equivalent worker delegation to produce `filter_results.json`.
11. Run `rss-enrich` on the selected subset.
12. If `rss-enrich` reports missing Chinese fields or entity completion tasks, the invoking agent should complete them before publish in production mode.
13. Build `daily-digest.json`.
14. Run `rss-publish`.
15. Run `rss-verify`.

## Required Artifacts

A successful production-quality run must produce all of the following:

- raw RSS bundle from `rss-collect`
- normalized JSON
- fetched JSON
- deduped JSON
- clustered JSON
- `prefilter_input.json`
- `prefilter_results.json`
- `filter_input.json`
- `filter_results.json`
- `enrich_results.json`
- final `daily-digest.json`
- publish output metadata
- verification output metadata

Missing artifacts are a failed run, not a warning.

## Subagent Policy

Batching belongs here, not inside worker skills.

Recommended defaults:

- use subagents for `rss-prefilter` and `rss-filter`
- batch large candidate sets rather than dumping the whole set into one worker
- keep `drop` items out of later stages
- run `rss-enrich` only on already-selected items
- only use `--auto-workers` for smoke tests, fixture generation, or debugging

The repository now provides an official artifact-level batching helper:

```bash
python3 skill/rss-daily/agent_batch_runner.py plan-prefilter --input rss-daily-output/<date>/prefilter_input.json --output-dir rss-daily-output/<date>/agent-batches/prefilter
python3 skill/rss-daily/agent_batch_runner.py merge-prefilter --input rss-daily-output/<date>/prefilter_input.json --batch-dir rss-daily-output/<date>/agent-batches/prefilter --output rss-daily-output/<date>/prefilter_results.json
python3 skill/rss-daily/agent_batch_runner.py plan-filter --input rss-daily-output/<date>/filter_input.json --output-dir rss-daily-output/<date>/agent-batches/filter
python3 skill/rss-daily/agent_batch_runner.py merge-filter --input rss-daily-output/<date>/filter_input.json --batch-dir rss-daily-output/<date>/agent-batches/filter --output rss-daily-output/<date>/filter_results.json
python3 skill/rss-daily/agent_batch_runner.py plan-enrich --input rss-daily-output/<date>/enrich_results.json --output-dir rss-daily-output/<date>/agent-batches/enrich
python3 skill/rss-daily/agent_batch_runner.py merge-enrich --input rss-daily-output/<date>/enrich_results.json --batch-dir rss-daily-output/<date>/agent-batches/enrich --output rss-daily-output/<date>/enrich_results.json
python3 skill/rss-daily/agent_batch_runner.py status --batch-dir rss-daily-output/<date>/agent-batches/enrich
```

Use this helper instead of ad-hoc one-off scripts when the invoking agent wants to fan out subagent work.

The contract is stage order and artifacts, not a specific concurrency model.

## Publish Rules

- Publish only selected items that passed `rss-filter`.
- Production daily runs should not rely on placeholder empty Chinese fields.
- If the user explicitly asks for a smoke-test publish, fallback Chinese text is acceptable only when clearly labeled as such.
- Source counts and digest summary text must reflect all published source types, not only WeChat or arXiv.
- If the page-facing output is misleading even though `rss-verify` passes, the run is not "good" yet.

## Helper Script Surface

```bash
python3 skill/rss-daily/run_daily.py daily --config followhub.yaml
python3 skill/rss-daily/run_daily.py daily --config followhub.yaml --auto-workers
```

This script is a helper, not the primary contract.

- normal agent-driven production use should treat it as a stage runner / artifact coordinator
- `--auto-workers` is for local end-to-end smoke testing
