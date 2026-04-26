# FollowHub 参考仓库技能分析

> 生成日期：2026-04-26
> 扫描范围：`ref/` 下 5 个参考仓库的功能与技能拆解

---

## 1. AI热点自动监控 — 4 个技能

| # | 技能 | 核心能力 | 外部依赖 |
|---|------|---------|---------|
| 1 | **Twitter 数据采集** | 高级搜索 API、多账号批量抓取、增量去重 | twitterapi.io |
| 2 | **数据管理** | 三模式存储(增量/每日/最新)、去重、统计、Markdown导出 | 无 |
| 3 | **AI 摘要生成** | OpenAI 兼容 API 调用、结构化摘要(thinking块清理) | OpenAI兼容API |
| 4 | **飞书通知** | Token管理、富文本消息、长文自动分片 | 飞书开放平台 |

**数据流**：Twitter Monitor → DataManager → Summarizer → FeishuSender

**技术栈**：Python, requests, twitterapi.io, OpenAI-compatible API, 飞书开放平台

---

## 2. evil-read-arxiv — 5 个技能

| # | 技能 | 核心能力 | 外部依赖 |
|---|------|---------|---------|
| 1 | **每日论文推荐** (start-my-day) | arXiv+Semantic Scholar 混合搜索、四维评分(相关性/新近性/热门度/质量) | arXiv API, Semantic Scholar API |
| 2 | **论文深度分析** (paper-analyze) | PDF下载、元数据提取、结构化分析笔记(中英文) | arXiv API |
| 3 | **论文图片提取** (extract-paper-images) | 优先源码包提取、备选PDF提取、图片索引生成 | PyMuPDF |
| 4 | **论文笔记搜索** (paper-search) | 标题/作者/关键词/领域搜索、相关性排序 | 无(Obsidian本地) |
| 5 | **顶会论文搜索** (conf-papers) | DBLP+Semantic Scholar、三维评分、年度推荐 | DBLP API, Semantic Scholar API |

**技能间依赖链**：

```
start-my-day → paper-analyze → extract-paper-images
conf-papers  → paper-analyze → extract-paper-images
```

**技术栈**：Python, arXiv API, Semantic Scholar API, DBLP API, PyMuPDF, Obsidian Vault

---

## 3. ArxivReader — 6 个技能

| # | 技能 | 核心能力 | 外部依赖 |
|---|------|---------|---------|
| 1 | **arXiv 论文抓取** | 分类抓取、每日更新、增量采集 | arXiv API |
| 2 | **翻译** | GPT 翻译标题/摘要(英→中) | OpenAI API |
| 3 | **关键词过滤** | 用户定义关键词筛选、相关性评分 | 无 |
| 4 | **邮件推送** | HTML 模板邮件、附件、SMTP 发送 | SMTP (QQ Mail等) |
| 5 | **Web 浏览界面** | FastAPI 服务、论文浏览/搜索 | FastAPI |
| 6 | **定时调度** | 自动化任务调度、日志记录 | APScheduler |

**数据流**：arXiv Fetcher → Translator → Keyword Filter → Email Sender + Web Server (由 Scheduler 驱动)

**技术栈**：Python, FastAPI, APScheduler, OpenAI API, SMTP

---

## 4. Arxiv-tracker — 8 个技能

| # | 技能 | 核心能力 | 外部依赖 |
|---|------|---------|---------|
| 1 | **搜索查询构建** | 多类别/关键词/排除过滤、布尔逻辑(AND/OR) | 无 |
| 2 | **arXiv API 检索** | 自动分页、重试回退、新鲜度过滤、去重 | arXiv API |
| 3 | **LLM 摘要/翻译** | 双语摘要、启发式回退(无LLM时) | OpenAI兼容API |
| 4 | **链接提取** | 论文文本/HTML/PDF中代码项目链接抓取 | requests, PyMuPDF |
| 5 | **多格式输出** | JSON/Markdown 导出 | 无 |
| 6 | **邮件通知** | HTML邮件+Markdown附件 | SMTP |
| 7 | **静态站点生成** | 主题化 HTML 站点、GitHub Pages 部署 | 无 |
| 8 | **自动化调度** | CLI + 内置调度器 + GitHub Actions | click, GitHub Actions |

**数据流**：Config → QueryBuilder → arXiv Client → Parser → Enrichment(链接提取/去重) → Summarizer → Output(JSON/MD/Email/Site)

**技术栈**：Python, click, feedparser, PyYAML, PyMuPDF, OpenAI API, SMTP, GitHub Actions

---

## 5. hermes-arxiv-agent — 5 个技能

| # | 技能 | 核心能力 | 外部依赖 |
|---|------|---------|---------|
| 1 | **论文发现与爬取** | 关键词监控、PDF下载、Excel去重记录 | arXiv API |
| 2 | **LLM 处理** | PDF解析提取作者机构、中文摘要生成(90-150字) | Hermes/LLM |
| 3 | **数据管理** | Excel记录、JSON导出、状态跟踪(待处理/已爬取) | openpyxl |
| 4 | **Web 浏览界面** | 论文浏览器、日期/关键词过滤、收藏功能 | http.server |
| 5 | **自动化部署** | Cron调度、飞书通知、GitHub Pages发布 | 飞书, GitHub |

**数据流**：monitor.py(搜索/下载) → new_papers.json → Hermes LLM(机构提取/摘要) → build_data.py → Web Viewer / GitHub Pages

**技术栈**：Python, openpyxl, pdfplumber, requests, http.server, 飞书, GitHub Pages

---

## 跨仓库技能重叠矩阵

| 技能能力 | AI热点 | evil-read | ArxivReader | Arxiv-tracker | hermes |
|---------|:------:|:--------:|:-----------:|:------------:|:-----:|
| arXiv 搜索/抓取 | — | ✓ | ✓ | ✓ | ✓ |
| LLM 摘要/翻译 | ✓ | — | ✓ | ✓ | ✓ |
| 数据管理/去重 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 邮件通知 | — | — | ✓ | ✓ | — |
| 飞书通知 | ✓ | — | — | — | ✓ |
| Web 浏览界面 | — | — | ✓ | ✓ | ✓ |
| 静态站点生成 | — | — | — | ✓ | ✓ |
| 定时调度 | ✓ | — | ✓ | ✓ | ✓ |
| Twitter/X 采集 | ✓ | — | — | — | — |
| 论文深度分析 | — | ✓ | — | — | ✓ |
| 论文图片提取 | — | ✓ | — | — | — |
| 顶会论文搜索 | — | ✓ | — | — | — |
| 代码链接提取 | — | — | — | ✓ | — |

---

## 最小技能集：覆盖全部仓库功能需要 10 个 Skill

| # | Skill 名称 | 覆盖的能力 | 复用仓库数 |
|---|-----------|-----------|-----------|
| 1 | `twitter-collector` | Twitter/X 数据采集 | 1 |
| 2 | `arxiv-collector` | arXiv 搜索/抓取/分页/重试 | **4** |
| 3 | `conf-collector` | 顶会论文搜索(DBLP+Semantic Scholar) | 1 |
| 4 | `paper-analyzer` | 论文深度分析/图片提取/元数据 | 2 |
| 5 | `llm-summarizer` | LLM 摘要/翻译/双语文本生成 | **4** |
| 6 | `data-manager` | 去重/多格式存储/状态跟踪 | **5** |
| 7 | `notifier` | 飞书/邮件多通道通知 | 3 |
| 8 | `site-generator` | 静态HTML站点生成/部署 | 2 |
| 9 | `web-viewer` | 论文浏览/搜索/收藏 Web界面 | 3 |
| 10 | `scheduler` | 定时调度/回填/失败恢复 | 3 |

### 实现优先级建议

| 优先级 | Skills | 理由 |
|-------|--------|------|
| **P0 核心** | `arxiv-collector` + `llm-summarizer` + `data-manager` | 4/5 个仓库都需要，构成管道骨架 |
| **P1 输出** | `notifier` + `site-generator` | 发布层必需，将处理结果送达用户 |
| **P2 扩展** | `twitter-collector` + `conf-collector` + `paper-analyzer` | 差异化采集源和深度分析能力 |
| **P3 体验** | `web-viewer` + `scheduler` | 运行时自动化和交互体验 |

---

## 各仓库最佳参考实现

| Skill | 最佳参考仓库 | 原因 |
|-------|------------|------|
| `twitter-collector` | AI热点自动监控 | 唯一实现，功能完整 |
| `arxiv-collector` | Arxiv-tracker | 最完善的检索：重试/分页/去重/布尔查询 |
| `conf-collector` | evil-read-arxiv | 唯一实现DBLP+Semantic Scholar顶会搜索 |
| `paper-analyzer` | evil-read-arxiv | 结构化分析笔记+图片提取最完整 |
| `llm-summarizer` | Arxiv-tracker | 双语摘要+启发式回退，最健壮 |
| `data-manager` | Arxiv-tracker | 多格式输出+去重状态最规范 |
| `notifier` | ArxivReader | 邮件+飞书双通道，覆盖最广 |
| `site-generator` | Arxiv-tracker | 主题化站点+GitHub Pages，最成熟 |
| `web-viewer` | ArxivReader | FastAPI方案，工程化程度最高 |
| `scheduler` | Arxiv-tracker | CLI+调度器+GitHub Actions，最灵活 |
