# 阶段 2：起点榜单发现

## 输入与前置条件

读取产品说明书、[开发契约](contracts.md)、阶段 0 榜单入口证据及阶段 1 的包与 DB。榜单访问也受阶段 0 对元数据方式的核验结论约束。此阶段只产生 `BookCandidate`，不抓书籍正文。

## 具体任务

1. **02.1 榜单解析**：实现单一 `QidianRankingProvider`，从阶段 0 确认的官方页面或允许的接口提取书籍 ID、URL、书名、作者、分类与原始名次。保留榜单原始排序；缺失书籍 ID、URL 或名次的记录不得用猜测值填充。离线 fixture 使用合成或脱敏结构，不提交真实章节内容。
2. **02.2 分页与冻结**：在 `max_candidates` 内依榜单顺序读取分页，去除同一次扫描中的重复书籍 ID，冻结候选序列和一个 `snapshot_at`。实测第二页的 `data-rid` 从 1 重置，但页面展示名次 `.rank-tag` 从 21 开始；跨页使用展示名次，不按页码推算。页面结构变化、空页或名次冲突要有明确错误，不能把不完整列表标成正常 Top N。内部 `run_candidates` 保存序列，供后续续跑使用。
3. **02.3 小规模核验**：用共享 Scraper 做有限的真实读取，人工比对首页与第二页的书名、书籍 ID、展示名次、URL 与解析结果；记录 URL、时间和结果，不在测试仓库保存页面正文。

## 交付物

稳定的榜单候选接口、分页处理、合成 fixture 测试和一次小规模核验记录。筛选后的名次不得重新编号；`snapshot_at` 是本次发现时间，不冒充平台发布的榜单日期。

## 验收命令

运行 `uv run python -m unittest discover -s tests/research`、`uv run ruff check research tests/research`、`uv run ruff format --check research tests/research`。真实核验只在阶段 0 允许的方式下进行，并将人工比对结果写入阶段 Issue；至少检查首页和分页边界。

## 失败时处理

若官方页面当前仅提供不完整榜单或无法确认原始名次，停止阶段出口并更新阶段 0 证据。遇到访问限制按 `blocked_access` 报告，不切换到规避方式。解析结构变化时先补失败 fixture，再修正解析器。
