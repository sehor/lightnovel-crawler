# 阶段 3：起点书籍、目录与章节 Source

## 输入与前置条件

读取产品说明书、[开发契约](contracts.md)、阶段 0 上游接缝记录，以及 Fork 的 `AGENTS.md` 和 `.claude/skills/add-source`。阶段 0 的正文访问结论必须为 `GO`，否则本阶段保持阻塞；本地合成 fixture 不改变该关口。

## 具体任务

1. **03.1 Source 接入**：以 Fork 当前推荐的 Source 基类或模板实现起点书籍适配，沿用上游 Source 注册、Scraper、限速和资源释放路径。平台解析留在起点模块，Research 层只调用稳定的书籍/目录/章节接口。若上游当前接口与阶段 0 记录不一致，先更新记录和契约。
2. **03.2 目录与免费状态**：从书籍 URL 取得稳定书籍 ID、目录序号、章节 ID/URL、标题和明确的公开免费状态。按目录原始顺序选开篇前五章；目录不足五章、任一章非免费或状态未知时交给 Research 层整本跳过。目录存在重复或序号缺口时报告解析错误，不凭标题推测顺序。
3. **03.3 正文与质量样例**：仅对已确认公开免费的章节读取正文。建立正常、空白、付费/登录提示、错误页、明显截断的合成或脱敏 fixture；验证清洗后字符数和 SHA-256。正文质量无法判断时返回不合格，不把错误提示保存为正文。
4. **03.4 单书验证**：在允许方式下，用一个文档化样本核对前五章目录顺序、免费状态、标题和正文；人工比对第 1 与第 5 章。运行频率遵守阶段 0 记录的限制，遇到拒绝访问即停并记录。

## 交付物

起点 Source、Research 调用接缝、离线质量测试和单书验证记录。Source 只负责平台解析，选书、去重和研究库存储留在阶段 4。不得提交采集到的小说正文或凭据。

## 验收命令

运行 `uv run python -m unittest discover -s tests/research`、`uv run ruff check research sources tests/research`、`uv run ruff format --check research sources tests/research`。Source 注册或基类受影响时运行 `uv run python -m lncrawl dev check-sources`。如上游 pyright 已覆盖新增 Source，运行其 lint 命令；单书核验在 Issue 中附实际结果而非正文。

## 失败时处理

被要求登录、付费、验证码或访问明确拒绝时停止该样本，标为 `unknown_access` 或 `blocked_access`，回到阶段 0 重新核验。若上游 Source 框架无法暴露免费状态，调整起点专属适配并更新契约，不在通用 Core 中加入起点特例。
