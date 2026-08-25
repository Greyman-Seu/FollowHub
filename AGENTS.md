# Repository Guidelines

## Project Structure & Module Organization

FollowHub is an agent-first collection of Python skills for collecting, filtering, enriching, and publishing arXiv and RSS content. Each capability lives under `skill/<skill-name>/`, typically with a `SKILL.md`, one entry-point script, and `tests/`. Shared orchestration is in `scripts/`; design notes and plans are in `docs/`. `ref/` contains reference projects, while `submodules/page_github` and `submodules/llm-wiki-skill` are independently versioned submodules.

Directories ending in `-output/` and `paper-assets/` contain generated or downloaded artifacts. Avoid editing them manually unless the task explicitly concerns fixtures or published data.

## Build, Test, and Development Commands

There is no monolithic build step. Run tools from the repository root with Python 3:

```bash
python3 skill/arxiv-collect/arxiv_collect.py run --mode daily --profile followhub.yaml
python3 skill/rss-daily/run_daily.py daily --config followhub.yaml
python3 -m unittest discover -s skill/arxiv-collect/tests -p 'test_*.py'
python3 -m unittest discover -s skill -p 'test_*.py'
```

Use a focused test directory while developing, then run the broader suite before submitting. Publishing commands such as `publish-daily` can change remote R2/page data; prefer `build-daily` or documented dry-run paths during validation.

## Coding Style & Naming Conventions

Use four-space indentation and standard-library-first Python. Follow existing type hints and keep CLI parsing separate from transformation logic. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_CASE` for constants. Skill directories use kebab-case (`rss-enrich`), entry scripts use snake_case (`rss_enrich.py`), and tests are named `test_<module>.py`. Keep JSON/YAML contracts explicit and backward compatible.

## Testing Guidelines

Tests use the standard `unittest` framework, including `unittest.mock`, temporary directories, and local fixtures. Add regression tests beside the affected skill. Mock network and cloud operations; tests must not publish, require credentials, or depend on live feeds. No fixed coverage threshold is configured, but new branches and failure handling should be exercised.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects such as `Fix wiki publish package layout` and `Tighten X daily filtering`. Keep each commit scoped to one behavior. Pull requests should explain the user-visible impact, list verification commands, identify configuration or data-contract changes, and link relevant issues. Include screenshots for viewer/page changes. Commit submodule pointer updates deliberately and mention the corresponding upstream change.

## Configuration & Secrets

Create local configuration from `*.example.yaml` files. Never commit API keys, R2 credentials, personal feed lists, or machine-specific paths. Review generated output before publishing and use historical-publish flags only when intentionally repairing prior dates.

## Persistent User Workflow

The user's primary day-to-day skills are `skill/daily/` and
`skill/arxiv-to-wiki/`; interpret `arxiv2wiki` as an alias for the latter. Read
the relevant `SKILL.md` before running or changing either workflow. Create new
skills and update existing skills under `skill/`, following the repository's
established layout and test conventions.

After completing requested skill or application changes, run appropriate tests,
review the diff, commit only the files belonging to the current task, and push
the resulting commit to the configured GitHub remote unless the user explicitly
asks not to push. Preserve unrelated dirty-worktree changes. For independently
versioned submodules, commit and push within the submodule first, then update the
parent repository pointer deliberately.
