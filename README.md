# followhub

`followhub` 是一个面向多源信息跟踪、摘要生成与网页发布的仓库。它的目标是把 X、公众号、arXiv 等平台上的高价值内容汇聚起来，生成每日摘要，并逐步演进为可由 agent 编排的 skill / tool 系统。

## 当前状态

当前仓库已完成第一轮产品与架构文档整理，核心文档位于 `company/` 目录。

## 文档入口

- 产品总览：`company/00-overview/followhub-product-overview.md`
- 总 PRD：`company/01-prd/prd-master.md`
- 第一阶段 PRD：`company/01-prd/prd-phase1-daily-brief.md`
- 系统架构：`company/02-architecture/system-architecture.md`
- 实施路线图：`company/03-planning/implementation-roadmap.md`

## 仓库结构

```text
followhub/
├── company/
│   ├── 00-overview/
│   ├── 01-prd/
│   ├── 02-architecture/
│   ├── 03-planning/
│   ├── 04-operations/
│   ├── 05-release/
│   └── 06-decisions/
├── docs/
├── scheduler/
├── skill/
├── sources/
└── storage/
```

## 后续方向

- 完成 Phase 1 端到端 pipeline 实现
- 生成本地静态日报页面
- 接入 `tenstep.top/follow/`
- 逐步将稳定能力抽象为 skill，并接入 Claude / Codex 等 agent
