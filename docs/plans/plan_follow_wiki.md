# Follow + Wiki Plan

## Goal

为 FollowHub 设计一个可长期扩展的内容入口：

- `follow`
  - 面向每天的增量信息消费
  - 聚合 arXiv、微信公众号、X、B 站等来源
  - 强调“今天有什么值得看”
- `wiki`
  - 面向主题知识沉淀
  - 强调“这个方向已经积累了什么”

核心原则：

- `follow` 和 `wiki` 平级存在
- `follow` 内部提供通向 `wiki` 的上下文入口
- 先定义页面和数据 contract，再让各个 source 适配

---

## Product Positioning

### `follow`

定位为 inbox / digest：

- 看最新
- 看每日推送
- 看跨来源聚合
- 看重点摘要

### `wiki`

定位为 knowledge base：

- 看主题定义
- 看长期知识沉淀
- 看代表论文 / 作者 / 项目 / 术语
- 看领域结构化索引

---

## Information Architecture

### Top-level Routes

- `/follow`
- `/wiki`
- `/wiki/domain/:slug`
- `/follow/day/:date`

后续可扩展：

- `/follow/source/:source_type`
- `/follow/domain/:slug`
- `/wiki/topic/:slug`

### Navigation

全局导航平级展示：

- `Follow`
- `Wiki`

`follow` 页面内部也要提供：

- 全局 `Open Wiki` 入口
- 领域卡片到 `wiki` 的入口
- 单条内容到相关 wiki topic / domain 的入口

---

## Follow Page Structure

### Upper Section: Domain Cards

上半部分展示“我关注的领域”。

每张卡片建议包含：

- 领域名
- 今日更新数
- 近 7 天更新数
- 最近 1 到 2 条重点
- `View Feed`
- `Open Wiki`

交互建议：

- 点击卡片主体：过滤下半部分时间轴
- 点击 `Open Wiki`：跳转到 `/wiki/domain/:slug`

### Lower Section: Daily Timeline

下半部分按时间轴展示每日 digest。

每一天是一张 digest card，结构分两层：

1. 日级摘要
   - 一句话总览
   - 3 到 5 条 highlights
   - 各来源计数 badge
2. 来源分组
   - `arXiv`
   - `微信公众号`
   - `X`
   - `Bilibili`

每个来源组默认可折叠。

不建议只做“纯链接汇总”：

- 纯链接汇总价值太低
- 时间轴会退化成书签列表

推荐做法：

- 摘要在上
- 链接明细在下
- 默认折叠细节

---

## Wiki Structure

### Wiki Home

`/wiki` 建议承担：

- 领域索引
- 热门主题
- 最近更新的知识页
- 搜索入口

### Domain Page

`/wiki/domain/:slug` 建议包含：

- 领域定义
- 关键问题
- 代表论文
- 关键作者 / 机构 / 项目
- 相关主题
- 来自 `follow` 的近期动态入口

---

## Data Model

## Core Principle

先定义统一 `follow` schema，再让 arXiv / 微信 / X / B 站分别适配。

### Suggested Daily Digest Schema

```json
{
  "date": "2026-05-02",
  "summary": "今天主要是 VLA 和机器人操作方向有更新，另有 1 篇公众号长文值得看。",
  "highlights": [
    "一篇 arXiv 论文把长程规划和 VLA 执行器解耦",
    "一篇公众号文章总结了具身数据合成路线",
    "X 上有一个值得跟进的 demo thread"
  ],
  "counts": {
    "arxiv": 12,
    "wechat": 3,
    "x": 8,
    "bilibili": 1
  },
  "sections": [
    {
      "source_type": "arxiv",
      "title": "arXiv",
      "count": 12,
      "items": []
    }
  ]
}
```

### Suggested Item Schema

```json
{
  "id": "arxiv:2604.21924",
  "source_type": "arxiv",
  "title": "Long-Horizon Manipulation via Trace-Conditioned VLA Planning",
  "summary": "把短程执行扩展到长程操作规划。",
  "importance": "high",
  "published_at": "2026-05-02T08:00:00Z",
  "domains": [
    {
      "name": "VLA",
      "slug": "vla"
    },
    {
      "name": "Embodied AI",
      "slug": "embodied-ai"
    }
  ],
  "tags": ["planning", "robot-manipulation"],
  "authors": ["Isabella Liu", "Sifei Liu"],
  "links": {
    "primary": "https://arxiv.org/abs/2604.21924",
    "pdf": "https://arxiv.org/pdf/2604.21924"
  },
  "wiki_refs": [
    {
      "type": "domain",
      "slug": "vla"
    }
  ],
  "meta": {
    "matched_domain": "Robotics",
    "relevance_score": 3.2,
    "overall_score": 2.8
  }
}
```

### Suggested Manifest Schema

```json
{
  "latest_date": "2026-05-02",
  "days": [
    {
      "date": "2026-05-02",
      "summary": "VLA 和机器人方向有明显更新。",
      "counts": {
        "arxiv": 12,
        "wechat": 3,
        "x": 8,
        "bilibili": 1
      },
      "path": "follow/daily/2026-05-02.json"
    }
  ],
  "domains": [
    {
      "name": "VLA",
      "slug": "vla",
      "today_count": 6,
      "week_count": 19,
      "wiki_path": "/wiki/domain/vla"
    }
  ]
}
```

---

## Storage and Delivery

## Recommended Architecture

推荐技术方案：

- `submodules/page_github`
  - 承担固定页面壳和前端交互
- `R2`
  - 存储 `follow` JSON
- `rcli`
  - 上传 JSON 到 R2

### Why Not Daily HTML as Main Output

不建议把“每天生成一整套 HTML”作为长期主方案，原因：

- 产物重复
- 多来源聚合后维护成本高
- 归档和 latest 切换麻烦
- page submodule 已经天然更适合做固定前端壳

### Recommended R2 Layout

```text
follow/manifest.json
follow/latest.json
follow/daily/2026-05-02.json
follow/daily/2026-05-01.json
follow/domain/vla.json
```

### Cache Strategy

- `follow/daily/YYYY-MM-DD.json`
  - 长缓存
  - 视为不可变
- `follow/latest.json`
  - 短缓存
  - 可覆盖
- `follow/manifest.json`
  - 短缓存
  - 可覆盖

---

## Role of Existing Skills

### `arxiv-find`

- 负责检索、daily、backfill、search
- 输出结构化论文结果

### `arxiv-enrich`

- 负责评分、摘要、单位、标签等 enrich 字段

### `arxiv-view`

当前定位：

- 适合作为 skill 内部 viewer
- 适合作为本地预览工具
- 适合作为数据 contract 的验证器

不建议直接把“每天一套 arxiv-view bundle”作为最终线上 Follow 页主发布方案。

### `rcli`

- 负责把 `follow` JSON 上传到 R2

---

## Todo

### Phase 1: Define Contract

- [ ] 定义 `follow` 页面线框
- [ ] 定义 `wiki` 页面最小路由
- [ ] 定义统一 daily digest schema
- [ ] 定义统一 source item schema
- [ ] 定义 manifest schema

### Phase 2: Build Follow Page

- [ ] 在 `page_github` 中增加 `/follow` 页面
- [ ] 实现领域卡片区
- [ ] 实现每日时间轴
- [ ] 实现来源分组折叠
- [ ] 实现 domain / source / date 过滤
- [ ] 实现 `Open Wiki` 入口

### Phase 3: Build Wiki Skeleton

- [ ] 在 `page_github` 中增加 `/wiki`
- [ ] 实现 `/wiki/domain/:slug`
- [ ] 先用 mock data 跑通 wiki 页面
- [ ] 定义领域知识页的最小 schema

### Phase 4: Adapt arXiv

- [ ] 把 arXiv 输出映射到统一 follow item schema
- [ ] 生成 daily digest JSON
- [ ] 生成 manifest.json
- [ ] 上传到 R2

### Phase 5: Add More Sources

- [ ] 微信公众号 source adapter
- [ ] X source adapter
- [ ] Bilibili source adapter
- [ ] 统一 importance / summary / domain tagging 逻辑

### Phase 6: Publish Workflow

- [ ] 设计 `follow publish` 工作流
- [ ] 通过 `rcli` 上传 JSON 到 R2
- [ ] `page_github` 页面 fetch R2 数据
- [ ] 验证 latest / archive / domain 页面联动

---

## Technical Decisions

### Decision 1

`follow` 和 `wiki` 平级，不做从属关系。

### Decision 2

`follow` 内部保留 wiki 上下文入口。

### Decision 3

页面采用“固定壳 + 动态 JSON”的主方案，而不是“每天一套 HTML bundle”。

### Decision 4

先统一 schema，再让 source 适配，不先对 arXiv 做特化。

### Decision 5

`arxiv-view` 继续保留，但作为内部 viewer / preview，而不是最终 Follow 主页面方案。

---

## Open Questions

- [ ] `follow` 页面是否需要 domain 详情子页，还是先只做过滤
- [ ] `wiki` 首页是否要先支持全文搜索
- [ ] `X / 微信 / B站` 的 item summary 是否统一由 agent 生成
- [ ] `importance` 是否要标准化成 `low / medium / high`
- [ ] 是否需要“只看 highlights”模式

---

## Immediate Next Step

下一步应当先做：

1. `follow` 页面线框
2. `follow` / `wiki` 路由草图
3. daily digest JSON schema 定稿

在这三件事完成前，不建议继续扩写某一个单独 source 的发布形态。
