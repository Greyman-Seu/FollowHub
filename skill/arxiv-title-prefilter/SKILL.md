---
name: arxiv-title-prefilter
description: Use when an agent needs a fast title/category-only screening pass before full arXiv filtering, deciding keep/drop/uncertain for batches of raw papers.
---

# arxiv-title-prefilter

Fast first-pass screening worker for arXiv papers.

## Role

`arxiv-title-prefilter` reviews a small batch of raw arXiv papers and returns a coarse routing decision:

- `keep`
- `drop`
- `uncertain`

It is not the final Follow decision maker.

It is a worker skill. It does not spawn subagents by itself.

## Input

The caller provides one paper or a small batch, usually 5-10 papers, with:

- `arxiv_id`
- `title`
- `categories`
- optional focus config from YAML:
  - `focus_definition`
  - `include_rules`
  - `exclude_rules`
  - `positive_examples`
  - `negative_examples`

This step should not rely on abstract-level reasoning unless the caller explicitly provides an abstract.

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

## Decision Standard

Use a recall-oriented policy:

- `keep`
  - clearly in the user's main line from title/category alone
- `drop`
  - clearly outside the user's main line from title/category alone
- `uncertain`
  - ambiguous from title/category alone
  - should advance to full `arxiv-filter`

This step should prefer false positives over false negatives.

## Output

Return only JSON:

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

## Rules

- Use only `keep`, `drop`, or `uncertain`.
- `uncertain` should be used liberally when the title is not decisive.
- Do not produce `domains`.
- Do not produce `one_liner_zh`.
- Do not produce `summary_cn`.
- Do not perform the final `include_in_follow` decision here.

## Boundary

`arxiv-title-prefilter` does not:

- fetch arXiv data
- read PDFs
- translate abstracts
- enrich metadata
- publish to R2
- decide the final Follow shortlist

Final include/exclude, domains, and Chinese text fields belong to `arxiv-filter`.
