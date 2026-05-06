---
name: arxiv-filter
description: Use when an agent or subagent needs to semantically filter arXiv papers for FollowHub, deciding inclusion, Follow domains, one-line Chinese summaries, Chinese abstracts, and review reasons.
---

# arxiv-filter

Semantic review worker for arXiv papers.

## Role

`arxiv-filter` reviews a small batch of raw or lightly enriched arXiv papers and returns structured selection results.

It is a worker skill. It does not spawn subagents by itself.

## Input

The caller provides one paper or a small batch, usually 3-5 papers, with:

- `arxiv_id`
- `title`
- `abstract_en`
- `summary`
- `authors`
- `categories`
- optional hints such as `matched_keywords`, `context_hits`, and `source_categories`
- a focus configuration from YAML, for example:
  - `focus_definition`
  - `include_rules`
  - `exclude_rules`
  - `positive_examples`
  - `negative_examples`

## Focus Source

Do not hard-code the user's current research focus inside this skill.

The caller should pass the current focus from config, preferably `followhub.yaml`, under a block such as:

```yaml
arxiv:
  filter_prompt:
    focus_definition: ...
    include_rules: [...]
    exclude_rules: [...]
    positive_examples: [...]
    negative_examples: [...]
```

This skill provides the judgment framework. The YAML provides the current topic scope.

## Output

Return only JSON:

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
      "reason": "简短说明为什么纳入或排除。"
    }
  ]
}
```

## Domain Meanings

- `LLM/VLM`: 大模型、多模态大模型，包含推理、训练等
- `Physical/Embodied Intelligence`: 物理/具身智能方向
- `AIGC`: 图像、视频与语音生成方向
- `Agent`: 工具调用、规划执行、工作流编排与智能体系统设计

Choose the best 1-2 domains only for included papers.

For included papers:

- `one_liner_zh` should be provided
- `summary_cn` should be provided
- `summary_cn` should be a faithful Chinese translation of the English abstract
- preserve model names, method names, and abbreviations in English when appropriate
- preserve numbers, metrics, and main experimental conclusions; do not silently drop them
- do not rewrite the abstract into a looser summary style
- if the first attempt is weak or incomplete, the caller should retry this worker
- follow the YAML focus block rather than stale hard-coded interests

For excluded papers:

- set `include_in_follow` to `false`
- `domains` may be empty
- still provide `reason`
- `one_liner_zh` and `summary_cn` may be empty

## Boundary

`arxiv-filter` does not:

- fetch arXiv data
- enrich author affiliations or code links
- publish to R2
- decide batch sizing or subagent fan-out

`arxiv-filter` should remain stable even if the user's research interests change.

Changing focus should normally require only a YAML update, not a skill rewrite.

Batch sizing and subagent orchestration belong to `arxiv-daily`.
