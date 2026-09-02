---
name: publish-source
description: Use when one analyzed wiki source note should be published for immediate online reading on the Page site, including R2 artifacts, page_github push, deployment wait, and public source-route verification.
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
- commit and push the synchronized Page data to `page_github/main`
- wait until `https://tenstep.top/wiki/source/<slug>` returns HTTP 200
- return the verified Page URL as the primary reading URL, plus R2 artifact URLs

## Inputs

- source slug
- wiki root
- page root
- FollowHub config path

## Output

- remote HTML URL for direct reading
- remote JSON URL for structured consumption
- verified online Page URL for normal user-facing reading

## Notes

- This skill is per-source only.
- It does not publish topic or synthesis structure.
- It does not replace `publish-wiki`.
- A successful R2 upload is not sufficient when the user asks to publish a Page; the Page repository push and live route verification are mandatory by default.
