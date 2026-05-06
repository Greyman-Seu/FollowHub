---
name: follow-publish
description: Use when FollowHub needs to turn daily follow digests or arXiv result files into page-ready Follow data artifacts, sync them into the page submodule, or prepare publishable JSON bundles for Follow pages.
---

# follow-publish

Package Follow daily digests into page-ready JSON artifacts and optionally derive those digests from arXiv result files.

## Invocation Model

- This skill is meant to be installed into Codex / Claude and invoked by an agent.
- The Python CLI is the internal tool surface used by the agent.
- The CLI is not intended to be the primary human-facing workflow.

## Config Convention

Preferred:

- use one unified FollowHub config file
- export `FOLLOWHUB_CONFIG=/path/to/followhub.yaml`

This skill reads:

- `follow:`
- `publish:`

and downstream upload work reads:

- `r2:`

## Responsibilities

- Build `manifest.json`, `latest.json`, `daily/*.json`, `sources/*.json`, and `domains.json`
- Convert arXiv result files into a first-pass Follow daily digest
- Merge same-day updates into an existing Follow daily digest
- Rebuild index files from existing daily digests
- Sync generated data into the page submodule for local build / deploy workflows
- Publish built artifacts to R2 by delegating upload work to `rcli`

## Safety Rule

Normal daily publishing should only update:

- `latest.json`
- `manifest.json`
- `domains.json`
- `sources/*.json`
- `daily/<today>.json`

It should not rewrite older `daily/*.json` entries by default.

Historical publish is maintenance-only and must be explicitly acknowledged.

## Domain Classification Rule

For arXiv items, domain classification should be decided by the invoking agent, not by static keyword rules alone.

Current canonical domain meanings:

- `LLM/VLM`
  - 大模型、多模态大模型，包含推理、训练等
- `Physical/Embodied Intelligence`
  - 物理/具身智能方向
- `AIGC`
  - 图像、视频与语音生成方向
- `Agent`
  - 工具调用、规划执行、工作流编排与智能体系统设计

The preferred workflow is:

1. agent reads the paper title / summary / links
2. agent assigns the best 1 or 2 domains
3. `follow-publish` packages the already-classified digest

If agent-side classification is unavailable, `follow-publish.py` should fall back to:

```json
{
  "domains": [
    {"slug": "uncategorized", "name": "Uncategorized"}
  ]
}
```

## Suggested Agent Prompt

When the agent needs to classify an arXiv paper into Follow domains, use this judgment standard:

```text
You are classifying one arXiv paper into FollowHub domains.

Choose the best 1 or 2 domains only.
Do not assign broad extra domains unless the paper clearly belongs there.

Domain meanings:
- LLM/VLM: 大模型、多模态大模型，包含推理、训练等
- Physical/Embodied Intelligence: 物理/具身智能方向
- AIGC: 图像、视频与语音生成方向
- Agent: 工具调用、规划执行、工作流编排与智能体系统设计

Return only:
{
  "domains": [
    {"slug": "...", "name": "..."}
  ]
}
```

## Agent Tool Surface

```bash
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py help
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py build-daily --input /path/to/follow-daily.json --output-dir ./follow-publish-out
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py build-from-arxiv --input /path/to/arxiv-find-output.json --output-dir ./follow-publish-out
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py publish-daily --input /path/to/follow-daily.json --remote-prefix follow --output-dir ./follow-publish-out
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py publish-daily --input /path/to/follow-daily.json --remote-prefix follow --output-dir ./follow-publish-out --allow-historical
python3 /home/tenstep/workspace/followhub/skill/follow-publish/follow_publish.py rebuild-index --daily-dir ./follow-history --output-dir ./follow-publish-out
```

## Notes

- The page-side target is JSON data, not a daily HTML bundle.
- `build-from-arxiv` is the current bridge for validating the arXiv -> Follow page workflow.
- `publish-daily` assumes daily digests are the source of truth and index files are derived.
- `publish-daily` should merge with any existing same-day remote digest before overwriting it.
- `publish-daily` rejects non-today digests unless `--allow-historical` is explicitly provided.
- `rebuild-index` is the maintenance path for rebuilding `manifest/latest/sources/domains` from daily history.
- Domain tagging in `build-from-arxiv` is placeholder-only and should eventually be replaced by agent-side judgment.
- The page submodule can consume generated JSON either by import-at-build-time or by later R2/runtime fetch migration.
