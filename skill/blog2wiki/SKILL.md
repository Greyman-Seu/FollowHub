---
name: blog2wiki
description: Analyze a technical blog or project article into a maintained FollowHub Wiki page, preserving source evidence, figures, disclosed facts and unknowns, then validate and publish the page. Use for non-arXiv URLs with explicit Wiki/page intent; route arXiv papers to arxiv-to-wiki.
---

# blog2wiki

Turn a blog into a substantial Chinese source page and connect it to the existing
Wiki. Accept a URL, an optional page title, and the user's priority questions.
`blog-to-wiki` is an alias. Work from the FollowHub root.

## Capture and read

1. Resolve the initialized Wiki from the task/configuration; the repository's
   usual root is `submodules/llm-wiki-skill/followhub-wiki`. Read its schema,
   purpose, vocabulary, index and relevant topics. Read the llm-wiki integration
   instructions when using its write/cache helpers. Honor current user scope.
2. Fetch the actual article, following redirects, and inspect useful figures,
   captions and media. Follow primary references only where needed to answer the
   user's questions. Prior work supplies context, not missing facts about the
   new system. Do not describe a video as watched when only its poster or caption
   was available.
3. Deduplicate against existing sources using original/canonical URL and title.
   Reuse the existing slug on updates. For a new page choose a stable lowercase
   title slug, e.g. `om-1`; honor the requested display title exactly.
4. Archive the source with the entry script:

   ```bash
   python3 skill/blog2wiki/blog2wiki.py \
     --url https://example.org/blog/model \
     --wiki-root submodules/llm-wiki-skill/followhub-wiki \
     --slug model
   ```

   `--html-file /tmp/article.html` accepts an already captured HTML document.
   Raw HTML, readable text and a media/link inventory go into a SHA256-addressed
   directory under `raw/articles/<slug>/`. Updates create new snapshots. The
   script only captures evidence; it does not analyze, integrate or publish.
   It does not execute JavaScript. If extraction is insufficient, use available
   browser tools or a local export. After one failed retry, report the actual
   access blocker rather than analyzing navigation or an error page.

## Analyze and author

Use the user's priorities to organize the analysis. For robotics blogs, useful
questions include system architecture, model inputs/outputs, training, hand or
other hardware, data pipeline/scale, and conclusions. These are a starting point,
not a mandatory robotics template for unrelated blogs.

Distinguish in reader-facing prose:

- **原文披露 / 作者宣称**: directly supported statements; link the source section.
- **分析推断**: the reasoning and its supporting observations.
- **未披露 / 待验证**: missing architecture, training or evaluation details.

Separate policy training from controller training, demonstrated embodiments
from claims of universality, per-task adaptation data from total training data,
and collection time from optimization time. Do not infer a VLM backbone,
language input, diffusion/flow objective, parameter count, sensor rate or dataset
size merely from familiar terminology. A demo is not a benchmark success rate.
Record denominators, experimental scope and uncertainty with numerical results.
Avoid full translations or large copied excerpts; write an original analysis.

Use the existing website-facing source contract:

- Frontmatter: `id`, `slug`, requested `title`, `type: source`,
  `material_type: blog`, `source_type: web`, `source_kind: blog_url`,
  `source_url`, `source_input`, `created`, `updated`, `date`, `authors`,
  `affiliation`, `related_organizations`, `related_companies`, `domains`, 1–2
  existing `tags`, `summary`, `links.original`, `raw_refs`, `related_topics`,
  `related_syntheses`, `confidence`, `status: analyzed`.
- Preserve the precision of the publication date (e.g. `2026-09`); acquisition
  date belongs in `created`/capture metadata. Do not fabricate a day.
- Use `hero_image` and `images` with actual figure URLs when useful, and place
  each image under the explanatory section. Use video posters only as explicitly
  labeled posters with links to the demo.
- Sections: `太长不看`, `直观理解`, `核心信息`, `来源与证据`, `背景与问题`,
  `方法`, `结果`, `洞察`, `风险与判断`, `相关主题`.
- Canonical bold blocks: background `**动机：**`, `**问题缺口：**`; method
  `**方法概述：**`, `**核心机制：**`, `**方法拆解：**` (at least 3 concrete
  bullets), `**关键要点：**` (at least 2); risks `**局限：**`,
  `**适用场景：**`, `**最终判断：**`.
- The shared checker enforces substantive background/method lengths and figure
  zones. Blog notes require `来源与证据` instead of paper abstract sections.
  Do not invent a paper abstract, arXiv ID, PDF or translation URL.
- The website renders structured method blocks. Keep essential detail and
  tables within these blocks; supplemental Markdown headings alone may not
  appear online. Verify the built page contains the user's priority analysis.
- The page sync parser uses `**核心结果：**` under results and `**核心 insight：**`,
  `**和已有方法的关系：**`, `**可借鉴点：**` under insights. Put a result table in
  `## 结果速览表`. Keep the hero's `太长不看` text free of Markdown links/formatting
  because that field is rendered as plain text. Do not place an organization
  homepage in `links.project`: the package builder currently treats that field
  as a code-link fallback. Check that `codeUrl` is empty when no code is disclosed.

## Integrate, validate and publish

Preview which source/topics will change. Use llm-wiki's `create-source-page.sh`
with the captured raw file for atomic writing/cache update. Attach to existing
topics in both directions; update index/log. Only change a synthesis if this
evidence changes a supported judgment. Maintain graph relationships through
the existing graph tools when available.

Run the same completeness checker used by arxiv-to-wiki (it recognizes
`material_type: blog`), before and after package generation:

```bash
python3 skill/arxiv-to-wiki/scripts/check_source_completeness.py \
  --wiki-root <wiki-root> --slug <slug>
bash submodules/llm-wiki-skill/scripts/validate-followhub-wiki.sh <wiki-root>
python3 submodules/llm-wiki-skill/scripts/build-followhub-wiki-package.py \
  <wiki-root> <package-dir> --pretty
python3 skill/arxiv-to-wiki/scripts/check_source_completeness.py \
  --wiki-root <wiki-root> --slug <slug> --package-dir <package-dir>
```

For a normal request to create a Wiki page, follow the established public Wiki
publication workflow; read `skill/publish-wiki/SKILL.md`. Explicit draft/local-only
requests stop before publication. Validate and review generated artifacts before
upload. Check that the package source preserves the title, original URL, web/blog
classification, detailed method/risk blocks and inline figure zones. Upload the
reviewed package and refresh the website through existing publishing tools.

Single-slug page sync does not update topic details or the full package. If topic
relations changed, publish their reviewed package data too. Avoid committing or
publishing unrelated dirty content; use an isolated staging checkout if needed.
Apply repository commit/push instructions to requested skill/code changes and
deliberately update submodule pointers only after their commits are pushed.

Finish only after the remote manifest, source JSON and actual public page agree.
HTTP 200 from a generic fallback page is insufficient. Verify the requested title
and substantive content, and inspect the rendered page when browser tooling is
available. Report the public link, key findings, and any real verification or
publication blocker. Do not send additional chat messages to other recipients.
