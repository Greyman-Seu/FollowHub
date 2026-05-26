# Wiki 工作流与页面规划

## 目标

把 wiki 系统稳定拆成两层：

- `llm-wiki-skill` 负责知识生产
- `page_github` 负责正式展示与阅读

保留本地图谱工具，但不再把单文件图谱页当成最终公开 wiki 的主要阅读界面。

## 核心原则

- `arxiv-to-wiki` 负责单篇论文分析、入库、默认单篇发布
- `update-wiki` 负责知识结构整理
- `publish-wiki` 负责整体结构发布
- 正式阅读页面放在 `submodules/page_github`
- `knowledge-graph.html` 保留为本地辅助图谱工具

## P0：工作流约定

### `arxiv-to-wiki`

定义为：

1. 分析单篇论文
2. 写入一篇 `source note`
3. 接入本地 `llm-wiki`
4. 默认触发 `publish-source`
5. 是否触发 `update-wiki` 由 agent 判断

`update-wiki` 不应成为每篇论文的固定后置步骤。

### `update-wiki`

只有在这些情况出现时才运行：

- 新论文明显扩展了已有 topic
- 已经积累出 3-5 篇相关 source，形成稳定簇
- 某个 topic / synthesis 已经值得更新
- 用户明确要求整理知识库结构

这些情况不要自动运行：

- 论文是孤立的
- 主要目标是尽快远程查看单篇解读
- 跑完只会造出很薄的 topic 页

### `publish-source`

`publish-source` 负责发布单篇 source note，使用户在 `arxiv-to-wiki` 完成后就能远程直接阅读这篇详细解读。

### `publish-wiki`

`publish-wiki` 负责发布结构层：

- topic
- synthesis
- graph
- index / overview

## P0：发布模型

推荐的发布链路：

```text
本地 llm-wiki markdown
-> 导出结构化数据
-> 上传到 R2
-> 在线前端读取结构化数据
```

不建议让在线前端把原始 markdown 作为主数据源直接解析。

### 推荐的 R2 目录结构

```text
/wiki/
  manifest.json
  sources.json
  topics.json
  synthesis.json
  graph-data.json
  source/
    <slug>.json
  topic/
    <slug>.json
  synthesis/
    <slug>.json

/wiki-assets/
  ...images...
```

## P0：质量标准

把现有 `OpenVLA` 笔记当成默认质量下限。

这意味着：

- 每个必需章节都要有 paper-specific 的实质内容
- `方法` 不能只复述标题，必须解释实际机制
- `结果` 在论文提供时必须包含具体对比对象或数字
- `洞察` 必须有真实判断，不能只是泛泛表扬
- 图在真正有帮助时必须加
- 有条件时应当带结果表

批量处理不是降低质量的理由。
如果吞吐压力出现，应减少批次或并发，而不是输出薄摘要卡片。

### 图像策略

- arXiv 输入：优先使用 HTML 图
- PDF 输入：优先 caption/page 对齐裁图
- 最后才回退到 embedded image extraction

## P1：正式页面架构

正式 wiki 页面应迁移到 `submodules/page_github`。

规划路由：

- `/wiki`
- `/wiki/papers`
- `/wiki/source/[slug]`
- `/wiki/topic/[slug]`
- `/wiki/synthesis/[slug]`
- `/wiki/graph`

### 页面职责

- `/wiki`
  - wiki 首页
  - 展示总览、精选条目、主要入口
- `/wiki/papers`
  - 论文卡片式浏览页
  - 支持搜索、排序、筛选
- `/wiki/source/[slug]`
  - 单篇论文完整阅读页
- `/wiki/topic/[slug]`
  - 成熟的跨论文 topic 页
- `/wiki/synthesis/[slug]`
  - 更高层的对比、综述、路线图
- `/wiki/graph`
  - 在线图谱导航页
  - 不承担主要长文阅读职责

## P1：数据流

保持仓库分层：

- `llm-wiki-skill`
  - 负责 markdown 与结构化导出
- `page_github`
  - 负责读取结构化数据并渲染页面

不要把知识生产和公开前端混成一个仓库。

## P1：图谱定位

`knowledge-graph.html` 保留为：

- 本地图谱工具
- 离线导航工具
- 结构检查与调试页面

不再继续把它往“正式公共 wiki 阅读器”方向硬推。

## P2：知识结构持续建设

后续继续做这些事：

- 给 source note 之间补显式链接
- 反复出现的概念逐步抽成实体页
- synthesis 作为强连接器继续增加
- 不要过早把只由一篇论文支撑的方向写成厚 topic

## P2：阅读体验增强

后续计划：

- `/wiki/papers` 支持 topic / tag / domain 过滤
- reader 支持上一篇 / 下一篇
- reader 支持更强的目录和图表跳转
- `publish-source` 后给出稳定远程 URL
- 图谱节点点击后跳正式 source/topic/synthesis 页面

## 近期实施顺序

1. 完成 `arxiv-to-wiki` / `paper-analyze` / `update-wiki` / `publish-*` 职责边界
2. 定义结构化导出数据契约
3. 实现 `publish-source`
4. 实现 `publish-wiki`
5. 在 `page_github` 中建设 `/wiki/papers`
6. 接上 `/wiki/source/[slug]` 的正式数据读取
7. 把图谱降级成辅助导航，而不是主阅读入口

## 当前进展

### 已完成

- `arxiv-to-wiki` / `paper-analyze` / `update-wiki` 职责边界已写入 skill
- `paper-analyze` 已加质量门，默认按 `OpenVLA` 标准输出
- `arXiv id / abs / pdf` 输入优先尝试 `html` 页面
- `wiki-sync-page` 已导出 `sources.json`、`topics.json`、`synthesis.json` 以及 detail JSON
- `publish-source` 已实现并验证，可发布单篇 HTML + JSON 到 R2
- `publish-wiki` 已实现并验证，可发布全量结构化数据与图谱资产到 R2
- `page_github` 已接入 `wiki-sync-page` 生成的 `sources.json`
- `/wiki/papers` 页面已建成第一版
- `/wiki/source/[slug]` 已能读取同步后的 source 数据
- topic / synthesis 页面已开始读取同步后的生成数据
- `/wiki/graph` 已有正式在线版本第一版，并读取同步后的 `graph-data.json`
- `/wiki/papers` 已支持搜索、排序、类型/主题/关键词过滤
- source reader 已支持上一篇 / 下一篇
- topic / synthesis 页面已切到正文优先的同步渲染
- `/wiki/graph` 已支持搜索与类型过滤
- `/wiki` 首页已重做成 atlas 入口，不再把 graph 当成主阅读入口
- `/wiki/domain` 页面已重做成稳定容器结构
- `knowledge-graph.html` 已被收敛为本地导航工具，而不是主要阅读入口

### 未完成

- `publish-source` / `publish-wiki` 与页面正式联调
- 远程正式域名上的在线阅读入口收口
