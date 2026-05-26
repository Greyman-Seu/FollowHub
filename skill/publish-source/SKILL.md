---
name: publish-source
description: Use when one analyzed wiki source note should be exported and published for immediate remote reading, including rendered HTML and source JSON upload to R2.
---

# publish-source

Publish one `llm-wiki` source note for immediate remote reading.

This skill is the default publish follow-up after `arxiv-to-wiki`.

## When To Use

Use this skill when:

- one source note already exists in `wiki/sources`
- the user wants to remotely read that paper digest now
- `update-wiki` is not required yet

## Responsibilities

- sync structured wiki data into `page_github` generated data
- render one source note into standalone HTML
- upload the HTML to R2
- upload the matching source JSON to R2
- return stable remote URLs

## Inputs

- source slug
- wiki root
- page root
- FollowHub config path

## Output

- remote HTML URL for direct reading
- remote JSON URL for structured consumption

## Notes

- This skill is per-source only.
- It does not publish topic or synthesis structure.
- It does not replace `publish-wiki`.
