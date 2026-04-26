# followhub

`followhub` 是一个面向多源信息跟踪、摘要生成与网页发布的仓库。它的目标是把 X、公众号、arXiv 等平台上的高价值内容汇聚起来，生成每日摘要，并逐步演进为可由 agent 编排的 skill / tool 系统。

## 当前状态

当前仓库已完成第一轮产品与架构文档整理，并已落地一个最小可运行的 arXiv Phase 1 slice：

- YAML 配置加载
- arXiv 抓取与标准化
- 单日报告 JSON 生成
- 静态日报、首页、归档页渲染
- 面向 agent 的稳定 CLI 和首个 skill 外壳

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
├── config.example.yaml
├── docs/
├── scheduler/
├── skill/
├── src/
├── sources/
├── tests/
└── storage/
```

## 当前可用命令

先从示例配置开始：

```bash
cp config.example.yaml config.yaml
export FOLLOWHUB_CONFIG="$PWD/config.yaml"
```

```bash
python3 skill/rcli/scripts/rcli.py check
python3 skill/rcli/scripts/rcli.py copyto ./xx.png images/xx.png --config-file ./config.yaml
```

## 状态文件

当前运行状态会写到：

- `data/state/runtime.json`：最近一次成功日期和作业摘要
- `data/state/YYYY-MM-DD.json`：单日分阶段状态

## Skill 入口

当前仓库内的 R2 上传 skill 位于 `skill/rcli/SKILL.md`，helper script 位于 `skill/rcli/scripts/rcli.py`。

仓库根下的 `config.example.yaml` 已经填好了当前 bucket 的固定信息：

- `account_id`: `55089addaf72336be3109073072340fd`
- `bucket`: `followhub`
- `public_base_url`: `https://followhub.tenstep.top`

你只需要补 `access_key_id` 和 `secret_access_key`。

当前约定是：

- skill 只编排命令
- CLI 提供稳定调用面
- 核心实现放在 `src/followhub/`

## 后续方向

- 完成 Phase 1 端到端 pipeline 实现
- 生成本地静态日报页面
- 接入 `tenstep.top/follow/`
- 逐步将稳定能力抽象为 skill，并接入 Claude / Codex 等 agent
