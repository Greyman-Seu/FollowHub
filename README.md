# followhub

`followhub` 是一个以 agent 为中心的技能仓库，当前重点是把 arXiv 检索、回补、图片定位和发布能力沉淀成可复用 skill，而不是优先做一套人手动操作的 CLI 产品。

## 当前现状

当前仓库已经落地了这些可复用 skill / skill-like 能力：

- `arxiv-daily`
  - prompt-only pipeline skill
  - 负责编排 `collect -> filter -> enrich -> publish`
- `arxiv-collect`
  - 面向 arXiv daily/backfill raw 抓取
  - daily 语义对齐 `ArxivReader` 的 category-wide `New submissions`
  - 不做最终语义过滤
- `arxiv-filter`
  - subagent worker skill
  - 负责 include/exclude、domain、一句话中文总结、中文摘要、原因
- `arxiv-enrich`
  - 面向入选 arXiv 论文的二次补全
  - 负责作者、单位、热度、链接、分数字段的稳定 contract
- `arxiv-view`
  - 面向 `arxiv-collect` / `arxiv-enrich` 结果的静态 HTML viewer
  - 支持 `daily / backfill / search`
  - 支持本地收藏和复制收藏 arXiv ID
- `arxiv-fig`
  - 从 arXiv 论文里提取全部图片，再由 agent 结合 caption 选出架构图、总览图等
- `rcli`
  - 面向 Cloudflare R2 的上传/列出/删除 helper
- `follow-publish`
  - 面向 Follow 页面数据打包
  - 支持从 Follow digest 或 arXiv 结果生成 page-ready JSON

另外，`ref/` 下已经整理了 4 个 GitHub 参考仓库为 submodule，并保留了一份人工分析文档用于后续 skill 设计：

- `ref/Arxiv-tracker`
- `ref/ArxivReader`
- `ref/evil-read-arxiv`
- `ref/hermes-arxiv-agent`
- `ref/ref-repos-skill-analysis.md`

`submodules/page_github` 也是一个独立 submodule，用于页面发布仓库。

## 使用原则

当前推荐的使用方式是：

- **agent 优先通过 skill 使用仓库能力**
- **CLI 是给 agent 调用的底层工具接口**

也就是说，后续大部分调用场景更接近：

- agent 读取 `skill/arxiv-find/SKILL.md`
- agent 读取 `skill/arxiv-daily/SKILL.md`
- agent 读取 `skill/arxiv-collect/SKILL.md`
- agent 读取 `skill/arxiv-filter/SKILL.md`
- agent 读取 `skill/arxiv-enrich/SKILL.md`
- agent 读取 `skill/arxiv-view/SKILL.md`
- agent 读取 `skill/arxiv-fig/SKILL.md`
- agent 读取 `skill/rcli/SKILL.md`
- agent 读取 `skill/follow-publish/SKILL.md`

而不是让人直接长期把这些脚本当成产品入口来记忆和操作。

CLI 仍然保留，原因是：

- 便于测试
- 便于 agent / skill 内部稳定调用
- 便于后续接到调度器或其他 agent runtime

## 当前重点 Skill

### `arxiv-daily`

路径：

- `skill/arxiv-daily/SKILL.md`

当前定位：

- prompt-only pipeline skill
- 不包含 Python 脚本
- 指导 agent 调用：
  - `arxiv-collect`
  - `arxiv-filter`
  - `arxiv-enrich`
  - `follow-publish`
  - `rcli`

推荐流程：

1. `arxiv-collect` 获取全量 raw daily/backfill。
2. 主 agent 按 `arxiv-filter` 的契约拆 subagent。
3. `arxiv-filter` 产出 `filter_results.json`。
4. 主 agent 只对入选论文调用 `arxiv-enrich`。
5. `follow-publish` 发布到 R2/page。

### `arxiv-collect`

路径：

- `skill/arxiv-collect/SKILL.md`
- `skill/arxiv-collect/arxiv_collect.py`

当前能力：

- `daily`
  - 优先读取 `arxiv.org/list/<category>/new`
  - 只取 `New submissions`
  - 再通过 arXiv API 按 `id_list` 补元数据
- `backfill`
  - 按天生成独立日报
  - 另外输出 1 份回补 overview
- raw 输出对齐 `ArxivReader` 的 category-wide daily 语义
- keywords / excludes / topic context 只作为下游提示，不作为最终过滤规则

agent 约定：

- `arxiv-collect` 只负责 raw 抓取
- 语义过滤交给 `arxiv-filter`
- 入选论文细节补全交给 `arxiv-enrich`

当前建议：

- 现在先手动执行，不需要定时任务
- 以后如果要自动化，再挂到 agent 调度层

手动执行示例：

```bash
python3 skill/arxiv-collect/arxiv_collect.py run --mode daily --profile followhub.yaml
python3 skill/arxiv-collect/arxiv_collect.py run --mode backfill --profile followhub.yaml --from-date 2026-04-24 --to-date 2026-04-27
```

### `arxiv-filter`

路径：

- `skill/arxiv-filter/SKILL.md`

当前定位：

- subagent worker skill
- 可单独使用，也可被 `arxiv-daily` 批量调度
- 输入 1-5 篇论文，输出：
  - `include_in_follow`
  - `domains`
  - `one_liner_zh`
  - `summary_cn`
  - `reason`

### `arxiv-enrich`

路径：

- `skill/arxiv-enrich/SKILL.md`
- `skill/arxiv-enrich/arxiv_enrich.py`

当前能力：

- `abstract_en`
- `one_liner_zh`
- `summary_cn`
- `first_affiliation`
- `affiliations`
- `code_urls / project_urls`
- `hot_score / quality_score / overall_score`

当前定位：

- 既可以单独处理已有结果文件
- 只对 `arxiv-filter` 入选论文做细节补全
- 更适合被 agent 当作 worker 调用，而不是让人直接长期操作 CLI

### `arxiv-view`

路径：

- `skill/arxiv-view/SKILL.md`
- `skill/arxiv-view/arxiv_view.py`
- `skill/arxiv-view/view_template/`

当前能力：

- 只消费 `arxiv-collect` / `arxiv-enrich` 输出
- 统一静态目录 viewer：`index.html + app.js + styles.css + data.json`
- 支持 `daily / backfill / search`
- 支持：
  - 搜索
  - 分类过滤
  - 日期过滤
  - 收藏
  - 复制收藏 arXiv ID
- 默认展示：
  - 标题
  - 热度 / 分数
  - 作者
  - 第一单位
  - 中文一句话总结
  - 中文总结
  - 英文摘要折叠

### `arxiv-fig`

路径：

- `skill/arxiv-fig/SKILL.md`
- `skill/arxiv-fig/arxiv_fig.py`

当前能力：

- HTML figure 抽取
- arXiv source package 抽取
- PDF fallback 抽取
- caption 解析

### `rcli`

路径：

- `skill/rcli/SKILL.md`
- `skill/rcli/scripts/rcli.py`

当前能力：

- R2 配置检查
- 上传单文件
- 生成公开 URL
- 作为发布型 skill 的底层 helper

### `follow-publish`

路径：

- `skill/follow-publish/SKILL.md`
- `skill/follow-publish/follow_publish.py`
- `skill/follow-publish/arxiv_domain_map.example.yaml`

当前能力：

- 生成 `manifest.json`、`latest.json`、`daily/*.json`、`sources/*.json`、`domains.json`
- 支持从 Follow digest JSON 直接构建页面数据
- 支持从 arXiv 结果构建第一版 Follow digest 并产出页面数据
- 支持同步到 page 子模块的数据目录

## 配置

当前推荐使用 **一个统一配置文件**，例如：

- `followhub.yaml`

建议流程：

```bash
cp followhub.example.yaml followhub.yaml
export FOLLOWHUB_CONFIG="$PWD/followhub.yaml"
```

各 skill 读取各自需要的 section：

- `arxiv-collect`
  - 读取 `arxiv:`
- `follow-publish`
  - 读取 `follow:` 和 `publish:`
- `rcli`
  - 读取 `r2:`（同时兼容旧 `rclone:`）
- `arxiv-daily`
  - prompt-only pipeline skill，指导 agent 把统一 config 传给下游 skill

当前前缀约定：

- `follow/`
  - 正式线上前缀
- `follow-dev/`
  - 开发前缀
- `follow-dev-test/`
  - 临时试验前缀

日常发布安全约束：

- 默认只允许发布今天的 `daily`
- 默认不允许覆盖历史 `daily/*.json`
- 默认不允许 delete / purge 远端对象

旧的示例文件仍保留用于兼容和参考：

- `config.example.yaml`
- `skill/arxiv-find/arxiv_profile.example.yaml`

仓库根下的 `config.example.yaml` 已经填好了当前 bucket 的固定信息：

- `account_id`: `55089addaf72336be3109073072340fd`
- `bucket`: `followhub`
- `public_base_url`: `https://followhub.tenstep.top`

你只需要补：

- `access_key_id`
- `secret_access_key`

## 仓库结构

```text
followhub/
├── .gitmodules
├── README.md
├── config.example.yaml
├── docs/
│   └── plans/
├── ref/
│   ├── Arxiv-tracker/          # submodule
│   ├── ArxivReader/            # submodule
│   ├── evil-read-arxiv/        # submodule
│   ├── hermes-arxiv-agent/     # submodule
│   ├── AI热点自动监控/          # 普通参考目录
│   └── ref-repos-skill-analysis.md
├── skill/
│   ├── arxiv-collect/
│   ├── arxiv-filter/
│   ├── arxiv-find/             # legacy compatibility
│   ├── arxiv-enrich/
│   ├── arxiv-view/
│   ├── arxiv-fig/
│   ├── arxiv-daily/
│   ├── follow-publish/
│   └── rcli/
└── submodules/
    └── page_github/            # submodule
```

## 当前还没做的事

- `arxiv-enrich` 强化
  - 当前以启发式 enrich 为主
  - 还没有把 `evil-read-arxiv` 的热门度 / 质量评分能力完整吸收
  - 还没有把 `ArxivReader` / `hermes` 的单位与中文总结补全做强
- `arxiv-daily`
  - 作为 prompt-only daily 入口 skill，负责指导 agent 串起 `collect -> filter -> enrich -> publish`
- 发布链路整合
  - `follow-publish` 已经落地第一版页面数据打包
  - 但还没有把整条 `arxiv -> follow page -> R2/page deploy` 链路完全自动化
- 定时调度
  - 当前不需要
  - 后期再接 agent 调度能力

## 开发约定

- 新能力优先沉淀为 `arxiv-xx` 风格的 skill
- skill 文档里要记录：
  - 需求快照
  - 设计模式
  - 输入输出边界
- 如无必要，不要把 HTML 渲染、调度、检索混进一个 skill
- daily/backfill 先用 `arxiv-collect` 获取全量 raw，再由主 agent 调度 `arxiv-filter` subagent 筛选。
- 多个 arXiv ID 的 enrich 场景，优先让主 agent 调度，`arxiv-enrich` 只处理 `arxiv-filter` 入选后的论文。
- `ref/` 下的参考仓库尽量保持为 submodule，便于追踪上游
