# Follow Execution Todo

## Current State

当前已经完成的关键能力：

- `arxiv-find`
  - daily / backfill / search
- `arxiv-enrich`
  - enrich / relevance / scoring / affiliations / links
- `arxiv-view`
  - 本地 viewer
- `follow-publish`
  - `build-daily`
  - `build-from-arxiv`
  - `publish-daily`
  - `rebuild-index`
- `rcli`
  - R2 配置已完成
  - `rclone` 可用
  - 开发前缀 `follow-dev/` 已发布成功
  - 试验前缀 `follow-dev-test/` 可用于临时实验
- `page_github`
  - `/follow`
  - `/follow/[source]`
  - `/wiki`
  - `/wiki/domain/[slug]`
  - 首页已可 hydrate 远端 `latest.json`
  - `/follow/arxiv` 已可 hydrate 远端 `sources/arxiv.json`

## Prefix Convention

- `follow/`
  - 正式线上前缀
- `follow-dev/`
  - 开发默认前缀
- `follow-dev-test/`
  - 临时试验前缀

## What Is Still Not Finished

### P0

- [ ] `/follow/x`、`/follow/wechat`、`/follow/bilibili`
  - 明确接入远端 `sources/*.json`
  - 与 `/follow/arxiv` 保持一致的数据消费模式
- [ ] 页面侧来源页轻量时间过滤
  - 非 arXiv 来源页也应显式支持 date filter
- [ ] `arxiv-daily` 接入 `follow-publish`
  - 形成 `arxiv result -> follow page data -> optional publish` 的统一入口

### P1

- [ ] `follow-publish` 的正式命令文案和 README 对齐
- [ ] page 侧 `follow` 数据加载路径进一步统一
  - 首页、来源页都从同一个 remote/local fallback 机制读取
- [ ] 增加 `follow-publish` 的 workflow 级测试
  - 包括 `arxiv-daily` 调 `follow-publish`

### P2

- [ ] `/follow` 首页摘要展示继续打磨
  - 更清晰地区分 digest / sources / domains
- [ ] `wiki` 页面继续打磨
  - 增加与 `follow` 的双向联动入口
- [ ] 清理 page_github 里的遗留 hint / warning

### Later

- [ ] paper-analyze skill
- [ ] source adapters for wechat / x / bilibili
- [ ] page runtime 直接读 R2 正式前缀 `follow/`
- [ ] 已读 / 收藏 / 是否沉淀到 wiki

## Execution Order

建议严格按这个顺序执行：

1. page 侧把全部来源页统一到远端 `sources/*.json`
2. 给非 arXiv 来源页补轻量时间过滤
3. 把 `arxiv-daily` 串到 `follow-publish`
4. 做一轮 workflow 级验证
5. 最后再优化 UI 和文档

## Why This Order

- 先完成 page 数据消费一致性
  - 避免不同来源页分别维护不同的数据模式
- 再完成 workflow 串联
  - 这样发布链路才真正闭环
- UI 优化放后面
  - 避免在未稳定 contract 上做表层设计

## Immediate Next Step

下一步立即执行：

- `/follow/x`
- `/follow/wechat`
- `/follow/bilibili`

统一接入远端 `sources/*.json`，并补轻量 date filter。
