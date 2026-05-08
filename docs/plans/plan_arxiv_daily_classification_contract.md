# arXiv Daily Filter Contract

## Goal

Define the contract between `arxiv-daily` and `arxiv-filter` workers.

`arxiv-daily` is prompt-only. It asks lower-level skills to produce artifacts and asks subagents to process `filter_tasks.json`.

## Flow

1. `arxiv-collect` produces raw daily/backfill JSON.
2. The main agent builds `title_prefilter_tasks.json` from raw papers.
3. The main agent spawns title-prefilter workers in batches.
4. Workers return `prefilter_results.json`.
5. The main agent builds `filter_tasks.json` from `keep + uncertain` papers.
6. The main agent spawns `arxiv-filter` workers in batches.
7. Workers return JSON fragments.
8. The main agent merges fragments into `filter_results.json`.
9. Selected papers are enriched with `arxiv-enrich`.
10. `follow-publish` publishes the final digest.

## Input Task File

Path:

- `title_prefilter_tasks.json`

Shape:

```json
{
  "input_path": "/path/to/arxiv-collect-output.json",
  "item_count": 137,
  "worker_plan": {
    "mode": "subagent",
    "worker_skill": "title-prefilter",
    "group_size": 10,
    "worker_count": 14,
    "groups": []
  }
}
```

Each task should include:

- `arxiv_id`
- `title`
- `categories`

## Output Prefilter Result File

Path:

- `prefilter_results.json`

Shape:

```json
{
  "items": [
    {
      "arxiv_id": "2605.xxxxx",
      "decision": "keep",
      "reason": "标题直接属于 VLA / 机器人操作主线。"
    }
  ]
}
```

## Input Full Filter Task File

Path:

- `filter_tasks.json`

Shape:

```json
{
  "input_path": "/path/to/arxiv-collect-output.json",
  "item_count": 137,
  "worker_plan": {
    "mode": "subagent",
    "worker_skill": "arxiv-filter",
    "group_size": 5,
    "worker_count": 28,
    "groups": [
      {
        "worker_id": "filter-01",
        "item_count": 5,
        "arxiv_ids": ["2605.xxxxx"],
        "tasks": []
      }
    ]
  }
}
```

Each task should include:

- `arxiv_id`
- `title`
- `abstract_en`
- `summary`
- `authors`
- `categories`
- optional hints such as `matched_keywords`, `context_hits`, and `source_categories`

## Output Result File

Path:

- `filter_results.json`

Shape:

```json
{
  "items": [
    {
      "arxiv_id": "2605.xxxxx",
      "include_in_follow": true,
      "domains": [
        {"slug": "physical-embodied-intelligence", "name": "Physical/Embodied Intelligence"}
      ],
      "one_liner_zh": "一句话说明论文核心贡献。",
      "summary_cn": "英文摘要的中文翻译，保持事实一致，不要额外发挥。",
      "reason": "纳入或排除原因。"
    }
  ]
}
```

## Rules

- Every raw paper should receive an include/exclude decision.
- Only `include_in_follow=true` papers are published.
- Excluded papers may have empty `domains`, `one_liner_zh`, and `summary_cn`, but must have `reason`.
- Included papers should have 1-2 domains.
- `summary_cn` is a faithful Chinese translation of the English abstract, produced by `arxiv-filter`.
- Model names, abbreviations, numbers, metrics, and main conclusions should be preserved in translation.
- If `include_in_follow=true`, `one_liner_zh` and `summary_cn` should be attempted in `arxiv-filter`.
- If a selected paper is missing Chinese summary fields, the main agent should retry `arxiv-filter` before publish, but the paper may still be published as an incomplete follow item if repair fails.

## Domain Definitions

- `LLM/VLM`
  - 大模型、多模态大模型，包含推理、训练等
- `Physical/Embodied Intelligence`
  - 物理/具身智能方向
- `AIGC`
  - 图像、视频与语音生成方向
- `Agent`
  - 工具调用、规划执行、工作流编排与智能体系统设计
