# R2 Publish Safety

## Goal

为 FollowHub 的日常发布链增加最小但明确的安全约束，避免 agent 在正常运行中误删或误覆盖历史数据。

## Data Layers

### Fact Layer

- `follow/daily/YYYY-MM-DD.json`

这是历史事实层，默认视为不可随意修改。

### Index Layer

- `follow/latest.json`
- `follow/manifest.json`
- `follow/domains.json`
- `follow/sources/*.json`

这是索引层，可以重建。

## Normal Daily Publish

日常发布只允许修改：

- `latest.json`
- `manifest.json`
- `domains.json`
- `sources/*.json`
- `daily/<today>.json`

默认不允许：

- 删除任何远端对象
- 修改旧日期的 `daily/*.json`
- 调用 `delete`
- 调用 `deletefile`
- 调用 `purge`

## Maintenance Mode

以下行为只能在维护模式中执行：

- 历史日文件修复
- 索引全量重建
- 历史对象删除

当前对应命令：

- `follow-publish rebuild-index`
- `follow-publish publish-daily --allow-historical`

## Agent Rules

日常 agent：

- 可以：
  - `copyto`
  - 写当天 daily
  - 重写索引
- 不可以：
  - `delete`
  - `deletefile`
  - `purge`
  - 覆盖非今天的 daily

## Current Enforcement

代码层已经落地的约束：

- `follow-publish publish-daily`
  - 默认只允许发布今天的 digest
  - 历史日期需要显式 `--allow-historical`

文档层已经落地的约束：

- `follow-publish/SKILL.md`
- `rcli/SKILL.md`

## Future Hardening

- 把 `rcli` 的 destructive commands 完全移出日常 agent 工作流
- 如果需要，可为正式发布 token 降权
- 如果需要，可把历史数据修复分离到单独 maintenance skill
