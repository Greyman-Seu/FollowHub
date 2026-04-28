# followhub

`followhub` 是一个以 agent 为中心的技能仓库，当前重点是把 arXiv 检索、回补、图片定位和发布能力沉淀成可复用 skill，而不是优先做一套人手动操作的 CLI 产品。

## 当前现状

当前仓库已经落地了 4 个可复用 skill / skill-like 能力：

- `arxiv-find`
  - 面向 arXiv 检索、日报、回补
  - 支持 `daily` / `backfill` / `search`
  - 日报语义锁定为 `New submissions`
  - 使用共享 YAML profile
- `arxiv-enrich`
  - 面向 arXiv 结果的二次补全
  - 负责摘要、单位、热度、链接、分数字段的稳定 contract
  - 也是 `arxiv-find` 的默认 enrich 阶段
- `arxiv-view`
  - 面向 `arxiv-find` / `arxiv-enrich` 结果的静态 HTML viewer
  - 支持 `daily / backfill / search`
  - 支持本地收藏和复制收藏 arXiv ID
- `arxiv-fig`
  - 从 arXiv 论文里提取全部图片，再由 agent 结合 caption 选出架构图、总览图等
- `rcli`
  - 面向 Cloudflare R2 的上传/列出/删除 helper

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
- **CLI 只是 skill 背后的执行层**

也就是说，后续大部分调用场景更接近：

- agent 读取 `skill/arxiv-find/SKILL.md`
- agent 读取 `skill/arxiv-enrich/SKILL.md`
- agent 读取 `skill/arxiv-view/SKILL.md`
- agent 读取 `skill/arxiv-fig/SKILL.md`
- agent 读取 `skill/rcli/SKILL.md`

而不是让人直接长期记忆具体脚本参数。

CLI 仍然保留，原因是：

- 便于测试
- 便于 skill 内部稳定调用
- 便于后续接到调度器或其他 agent runtime

## 当前重点 Skill

### `arxiv-find`

路径：

- `skill/arxiv-find/SKILL.md`
- `skill/arxiv-find/arxiv_find.py`
- `skill/arxiv-find/arxiv_profile.example.yaml`

当前能力：

- `daily`
  - 优先读取 `arxiv.org/list/<category>/new`
  - 只取 `New submissions`
  - 再通过 arXiv API 按 `id_list` 补元数据
- `backfill`
  - 按天生成独立日报
  - 另外输出 1 份回补 overview
- `search`
  - 支持关键词、分类、排除词、分页
- `favorites`
  - 对齐 `ArxivReader` 的关注领域概念
- 默认 enrich
  - 默认接入 `arxiv-enrich`
  - 输出会尽量带上稳定的 enrich 字段，而不是只给薄元数据

agent 约定：

- 单个 arXiv ID：主 agent 可直接处理
- 多个 arXiv ID：优先由 `arxiv-find` 负责 orchestration，把 `arxiv-enrich` 作为 subagent worker 使用

当前建议：

- 现在先手动执行，不需要定时任务
- 以后如果要自动化，再挂到 agent 调度层

手动执行示例：

```bash
python3 skill/arxiv-find/arxiv_find.py run --mode daily --profile skill/arxiv-find/arxiv_profile.example.yaml
python3 skill/arxiv-find/arxiv_find.py run --mode backfill --profile skill/arxiv-find/arxiv_profile.example.yaml --from-date 2026-04-24 --to-date 2026-04-27
python3 skill/arxiv-find/arxiv_find.py run --mode search --profile skill/arxiv-find/arxiv_profile.example.yaml
```

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
- 也是 `arxiv-find` 默认内部 enrich 阶段
- 更适合被 agent 当作 worker 调用，而不是让人直接长期操作 CLI

### `arxiv-view`

路径：

- `skill/arxiv-view/SKILL.md`
- `skill/arxiv-view/arxiv_view.py`
- `skill/arxiv-view/view_template/`

当前能力：

- 只消费 `arxiv-find` / `arxiv-enrich` 输出
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

## 配置

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
│   ├── arxiv-find/
│   ├── arxiv-enrich/
│   ├── arxiv-view/
│   ├── arxiv-fig/
│   └── rcli/
└── submodules/
    └── page_github/            # submodule
```

## 当前还没做的事

- `arxiv-enrich` 强化
  - 当前以启发式 enrich 为主
  - 还没有把 `evil-read-arxiv` 的热门度 / 质量评分能力完整吸收
  - 还没有把 `ArxivReader` / `hermes` 的单位与中文总结补全做强
- `arxiv-workflow`
  - 还没有落地统一 orchestrator skill
  - 后续负责串起 `find -> enrich -> view -> publish`
- 发布链路整合
  - 还没有把 `arxiv-view` 产物直接接到 `page_github` / R2
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
- 多个 arXiv ID 的 enrich 场景，优先让主 agent 调度，`arxiv-enrich` 作为 subagent worker
- `ref/` 下的参考仓库尽量保持为 submodule，便于追踪上游
