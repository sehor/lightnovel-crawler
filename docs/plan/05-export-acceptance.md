# 阶段 5：导出与 MVP 验收

## 输入与前置条件

读取产品说明书、[开发契约](contracts.md)和阶段 4 的运行状态。只有阶段 0 为 `GO` 且阶段 1—4 的出口已通过，才能进行真实正文验收。导出仅面向本地私人研究。

## 具体任务

1. **05.1 JSONL**：按 `run_id` 从入选书与章节生成 `books.jsonl`、`chapters.jsonl`，包含契约中的榜单、原始名次、快照时间、章节正文与 Hash。固定字段名和稳定排序；跳过候选不得出现。先写临时文件，全部成功后替换目标文件。
2. **05.2 Parquet**：用 uv 管理所需依赖，实现与 JSONL 同字段、同类型含义和同记录数的 `books.parquet`、`chapters.parquet`。空数据、写入失败和目标目录不可写时给出清楚错误，不留下混合新旧文件。
3. **05.3 离线交叉核对**：用合成数据验证 SQLite、JSONL、Parquet 的书籍/章节键、行数、原始名次、正文字符数和 Hash 一致。覆盖重复导出及导出中断，确认正文数据、DB 和导出目录都在 `.gitignore` 中。
4. **05.4 真实验收**：在允许方式下执行默认采集，目标 10 本合格书 × 5 章。检查每本五章连续、均公开免费、正文有效，核对原始名次和导出一致性；再做重复运行及中断续跑。记录运行 ID、时间、扫描/跳过/失败统计、验证命令和非正文证据。若榜单可用候选不足，报告 `partial` 和实际覆盖，不宣称 MVP 已达标。

## 交付物

两个本地导出格式、可重复的离线核对、真实验收报告。报告只放统计、字段校验、Hash 比对结果及问题，不附小说正文。真实数据保留在本机，不提交仓库或 GitHub Issue。

## 验收命令

运行 `uv run python -m unittest discover -s tests/research`、`uv run ruff check research tests/research`、`uv run ruff format --check research tests/research`、`uv build`。真实命令示例：`uv run python -m research collect`，随后对返回的 `RUN_ID` 执行 `status`、两次 `export`。用本地脚本或测试核对每种格式恰好 10 本、50 章、名次一致且无重复键。

## 失败时处理

导出行数或 Hash 与 DB 不符时不得发布验收通过，先定位格式或查询错误。真实采集未达 10 本时保留 `partial` 结果与原因；因访问限制停下时标记 `blocked_access` 并回到阶段 0。只有全部四项产品成功标准满足，才关闭 MVP 父 Issue。
