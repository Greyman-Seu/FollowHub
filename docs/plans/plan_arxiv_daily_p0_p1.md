# arXiv Daily P0/P1

## P0

- 保留 `cs.RO`、`cs.AI`、`cs.LG` 作为主抓取类别
- `daily` / `backfill` 输出分两层：
  - raw candidates
  - publish shortlist
- agent 分类结果除 `domains` 外，增加：
  - `include_in_follow: true|false`
- `publish-follow` 默认只发布 shortlist

## P1

- 对 metadata hydration / enrich worker 做并发优化
- 页面上明确区分 raw candidate 语义与 shortlist 语义
- 文档写清：
  - 抓取层宽
  - 发布层窄
