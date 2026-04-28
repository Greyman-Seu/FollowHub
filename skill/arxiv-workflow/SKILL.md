---
name: arxiv-workflow
description: Use when an agent needs the top-level arXiv workflow entrypoint that coordinates arxiv-find, arxiv-enrich, and arxiv-view, especially when multiple paper IDs should be split into subagent enrich work.
---

# arxiv-workflow

High-level agent entrypoint for the FollowHub arXiv pipeline.

## Requirements Snapshot

- Serve as the agent-facing orchestrator.
- Compose `arxiv-find` outputs into a ready-to-review viewer bundle.
- When multiple arXiv IDs are selected, prefer subagent-style enrich work planning.
- Keep `arxiv-enrich` as the worker and `arxiv-view` as the render layer.

## Role Split

- `arxiv-find`
  - retrieve and normalize
- `arxiv-enrich`
  - enrich worker
- `arxiv-view`
  - render-only static viewer
- `arxiv-workflow`
  - orchestrate the chain

## Commands

```bash
python3 /home/tenstep/workspace/followhub/skill/arxiv-workflow/arxiv_workflow.py help
python3 /home/tenstep/workspace/followhub/skill/arxiv-workflow/arxiv_workflow.py compose --input /path/to/arxiv-find-output --workspace ./workflow-out
```

## Notes

- The script generates a `workflow.json` manifest for agents.
- The script does not spawn subagents itself.
- The invoking agent should use `workflow.json` to fan out enrich work when needed.
