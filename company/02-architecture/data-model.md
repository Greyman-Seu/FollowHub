# 数据模型

## 1. 原始条目模型

建议统一条目至少包含以下字段：

- `id`
- `source_type`
- `source_name`
- `author`
- `published_at`
- `title`
- `url`
- `content_raw`
- `assets`
- `metadata`
- `fetched_at`

## 2. 理解结果模型

- `summary_short`
- `importance_level`
- `interest_relevance`
- `reason_to_read`
- `tags`
- `translation_url`

## 3. 日报模型

- `date`
- `time_range`
- `sources_summary`
- `highlights`
- `categorized_items`
- `paper_section`
- `full_feed`
- `generation_meta`

## 4. 状态模型

- `last_successful_date`
- `jobs`
- `source_runs`
- `render_runs`
- `errors`
