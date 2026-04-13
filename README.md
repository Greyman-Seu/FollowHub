# followhub

`followhub` is a repository for a future skill and scheduled tool that follows the latest information from multiple sources, including X, WeChat Official Accounts, and arXiv.

## Goal

The repository is intended to evolve into a unified information-following system that can:

- fetch updates from multiple sources
- normalize and rank items
- store recent results
- trigger on a schedule
- expose a reusable skill or automation entrypoint

## Planned Scope

Initial source targets:

- X
- WeChat Official Accounts
- arXiv

Potential future extensions:

- RSS
- GitHub releases
- newsletters
- websites with change tracking

## Repository Layout

```text
followhub/
├── README.md
├── .gitignore
├── docs/
│   └── notes/
├── skill/
│   └── README.md
├── scheduler/
│   └── README.md
├── sources/
│   └── README.md
└── storage/
    └── .gitkeep
```

## Design Direction

This repository should stay source-agnostic at the top level:

- `sources/` contains fetchers or adapters for each upstream platform
- `scheduler/` contains periodic execution logic
- `skill/` contains the skill-facing wrapper or orchestration entrypoint
- `storage/` is reserved for local cache, snapshots, or derived artifacts

## Status

Repository initialized. Implementation is intentionally not started yet.
