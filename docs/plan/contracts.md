# MVP 开发契约

本文件定义阶段 1—5 共用的接口与数据含义。阶段 0 若发现上游接口与此处实现建议冲突，先更新本文件并记录依据，再开始依赖它的 Issue。产品目标见 [产品说明书](../../网文开篇研究采集器-产品说明书.md)。

## CLI

入口为 `uv run python -m research`，命令如下：

```text
collect [--target-books 10] [--chapters 5] [--max-candidates 50] [--db data/research.db]
resume --run-id RUN_ID [--db data/research.db]
export --run-id RUN_ID --format jsonl|parquet --output DIR [--db data/research.db]
status --run-id RUN_ID [--db data/research.db]
```

MVP 只支持 `qidian` / `newcomer-signed` 这一组平台与榜单；CLI 暂不开放任意平台或分类参数。`target-books` 是合格书目标，`max-candidates` 是最多检查的原始榜单候选数，必须不小于目标数。`chapters` 表示从目录开头起连续检查并完整保存的章节数，默认 5。验收使用默认值；改变参数不改变数据模型。运行结束输出 `run_id`、扫描数、入选数、跳过数、失败数及最终状态。

退出码：`0` 为目标达成，`2` 为扫描上限内未达目标，`3` 为访问方式受限或权限关口未通过，`1` 为其他运行错误。`status` 和 `export` 的成功退出码为 `0`；找不到 `run_id` 或格式错误为 `1`。

## 采集接口

`RankingProvider` 只产出榜单候选，不抓正文。每个 `BookCandidate` 至少含 `platform`、`ranking_id`、`external_book_id`、`book_url`、`title`、`author`、可空 `category`、`original_rank`。同一次发现先冻结候选顺序及 `snapshot_at`，再逐书处理。`original_rank` 取起点榜单实际名次，不能因筛选而重排。

起点 Source 负责书籍详情、目录顺序、公开免费状态和正文解析。Research 层按目录前 `N` 章逐章判定：任何一章不足、非公开免费或正文无效，整本不入选；只采集和保存完全合格的书。无法判断免费状态时按不合格处理。授权或访问方式不明确时停止正文流程，不尝试登录、付费、验证码处理或访问控制规避。

正文有效的最低判定：去除页面结构后有非空实质文本，且不是登录/付费/错误提示或明显截断。具体可复现的站点判定样例放在阶段 3 离线 fixture 中，不在通用层硬编码平台文案。

## SQLite 与运行状态

研究库独立于上游应用数据库；默认 `data/research.db`，数据库与导出目录加入 `.gitignore`。时间统一以带时区的 UTC 时间戳保存。

| 表 | 必要字段与约束 |
| --- | --- |
| `books` | `id`、`platform`、`external_book_id`、`title`、`author`、`category`、`book_url`；`(platform, external_book_id)` 唯一 |
| `chapters` | `id`、`book_id`、`source_chapter_key`、`chapter_no`、`title`、`source_url`、`text`、`char_count`、`is_free`、`fetched_at`、`content_hash`；`(book_id, source_chapter_key)` 唯一 |
| `collection_runs` | `run_id`、`platform`、`ranking_id`、`snapshot_at`、起止时间、目标书数、章数、扫描上限、各类计数、`status` |
| `run_candidates` | `run_id`、候选书 ID、原始名次、处理状态与原因；只用于冻结扫描顺序和续跑，不作为研究数据导出 |
| `ranking_entries` | `run_id`、`book_id`、`original_rank`；只记录入选书，`(run_id, book_id)` 唯一 |

`source_chapter_key` 优先用平台章节 ID；没有 ID 时使用规范化的来源 URL。`content_hash` 对标准化后的正文计算 SHA-256，用于质量核对，不作为跨书唯一键。书籍与五章、对应榜单名次在单个数据库事务中提交；未完成的书不留下部分章节。重复运行可复用已完成且仍满足规则的章节，不重复下载；新运行仍产生自己的名次记录。

运行状态为 `running`、`completed`、`partial`、`failed`、`blocked_access`。`completed` 仅在入选数达到目标且每本均有指定章数时使用。`partial` 表示扫描上限内未达目标。单书错误记录在 `run_candidates` 的原因分类及运行统计中，后续候选继续处理；平台访问明确拒绝时停止并标记 `blocked_access`。恢复同一运行时使用冻结的候选序列，已完成候选不重复处理。

跳过的候选可以在内部运行记录中保留 ID、原始名次和原因，**不得写入 `books`、`chapters` 或研究导出**。原因至少区分 `insufficient_free_chapters`、`invalid_body`、`fetch_error`、`unknown_access`。日志只记录诊断信息，不输出章节正文或凭据。

## 导出

`export` 只导出指定 `run_id` 的入选书：在输出目录生成 `books.jsonl` 与 `chapters.jsonl`，或对应的 `books.parquet` 与 `chapters.parquet`。书籍行由 `books` 与 `ranking_entries` 合成，包含 `run_id`、榜单标识、`snapshot_at` 和 `original_rank`；章节行用书籍的 `(platform, external_book_id)` 关联。两种格式字段名、类型和行数一致；章节正文在 `chapters` 文件中。导出采用临时文件后原子替换，失败不得留下看似完整的结果。
