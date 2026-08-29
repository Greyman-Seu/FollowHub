---
name: daily
description: Use when the user asks to run, publish, backfill, or check today's FollowHub daily. Run arXiv and RSS on weekdays, RSS only on Saturday and Sunday, and publish the completed results to the Follow page unless the user explicitly limits the request to one source.
---

# Daily

Run FollowHub's production daily pipelines as one coordinated workflow:

- `arxiv-daily`
- `rss-daily`

The combined daily workflow is date-aware in Asia/Shanghai:

- Monday through Friday: run both `arxiv-daily` and `rss-daily`.
- Saturday and Sunday: run `rss-daily` only; do not collect, process, publish, or verify arXiv, and require the day's arXiv count and same-day source item count to be zero.

An explicit source-specific request such as “run arXiv daily only” remains outside this combined schedule and may run that source independently.

## Procedure

1. Resolve `FOLLOWHUB_CONFIG` or repo-local `followhub.yaml`.
2. Determine the requested date in Asia/Shanghai and apply the weekday/weekend policy above.
3. On weekdays, start raw acquisition for arXiv and RSS concurrently. On weekends, start RSS only.
4. Run each scheduled pipeline according to its own `SKILL.md` contract:
   - `arxiv-daily`: collect → title-prefilter → filter → enrich → publish → verify
   - `rss-daily`: collect → normalize → fetch → dedupe → cluster → prefilter → filter → enrich → digest → publish → verify
5. Delegate all paper/item-level review and completion work to subagents or equivalent worker delegation. The main agent only orchestrates batches, validates and merges artifacts, invokes deterministic tools, and verifies publication.
6. Publish each completed scheduled pipeline independently. Weekday same-day publish operations must preserve and merge the other source sections through the existing Follow publish path. Weekend publishes must contain the RSS result with no arXiv items and an arXiv count of zero; an empty arXiv section emitted by the common digest schema is allowed.
7. Verify the final page data contains every scheduled update:
   - `follow/latest.json`
   - `follow/daily/YYYY-MM-DD.json`
   - affected `follow/sources/*.json`

## Retry Rule

When a worker times out, is unavailable, or emits invalid artifacts, keep that pipeline pending at its current stage and retry delegation with a fresh subagent. Do not replace worker judgments with main-agent decisions, `--auto-workers`, or heuristic production output. A successfully completed sibling pipeline may still publish while the other continues retrying.

## Reporting

Report the arXiv and RSS status separately, including raw counts, selected counts, published paths, verification result, and any pipeline still pending retries. On weekends, report arXiv as skipped by schedule rather than failed or pending.

## Scheduled Automation

For an unattended workstation, install the user-level systemd timer:

```bash
python3 skill/daily/scripts/install_scheduled_daily.py
```

The timer runs at 07:00 Asia/Shanghai and then every two hours through 23:00. The runner:

- uses a per-date file lock so attempts cannot overlap
- keeps the daily timer active on weekends for RSS while skipping arXiv by the Asia/Shanghai run date
- checks local verification artifacts and the actual R2 JSON before starting Codex
- runs Codex in an unattended environment, so worker fan-out must use standalone/equivalent delegation instead of collaboration-thread subagents
- by default treats all configured X/Twitter RSS feeds failing acquisition as incomplete, even if other sources published successfully
- can mark specific source families optional with `--allow-unavailable-source <source>` so verified remaining sources still publish while the outage is reported
- writes a dated success marker only when `latest`, `daily`, and affected source files all match
- skips every remaining trigger for that date after success
- leaves failed or incomplete runs unmarked so the next two-hour trigger retries
- can send one pending notification before the final retry when `--notify-pending-once` is enabled
- can send one bot notification with the Follow link after success and one failure notification after the final 23:00 retry

To enable notifications for a P2P chat:

```bash
python3 skill/daily/scripts/install_scheduled_daily.py \
  --notify-chat-id <oc_chat_id> \
  --summary-url https://tenstep.top/follow/
```

If X/Twitter should not block the daily publish on this workstation:

```bash
python3 skill/daily/scripts/install_scheduled_daily.py \
  --notify-chat-id <oc_chat_id> \
  --summary-url https://tenstep.top/follow/ \
  --allow-unavailable-source x \
  --notify-pending-once
```

Inspect it with:

```bash
systemctl --user status followhub-daily.timer
systemctl --user list-timers followhub-daily.timer
journalctl --user -u followhub-daily.service
```
