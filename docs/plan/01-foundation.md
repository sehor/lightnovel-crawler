# 阶段 1：Research 基础设施

## 输入与前置条件

读取产品说明书、[开发契约](contracts.md)和阶段 0 的 Fork 基线记录。阶段 0 `BLOCKED` 时，本阶段只可构建本地模拟与元数据基础，不接入正文网络请求。修改上游文件前遵守 Fork 内 `AGENTS.md`。

## 具体任务

1. **01.1 包与命令入口**：在 Fork 根目录新增 `research/` 包、`__main__.py` 与 Typer CLI，按契约实现 `collect`、`resume`、`export`、`status` 的参数解析和清晰的未实现提示。修改 `pyproject.toml` 的 package discovery，使安装包包含 `research*`；用 `uv build` 检查 wheel 内容，不仅依赖源码目录运行成功。
2. **01.2 独立 SQLite**：建立 `books`、`chapters`、`collection_runs`、`run_candidates`、`ranking_entries` 及索引/唯一约束。研究 DB 默认 `data/research.db`，不修改上游 DAO 或 Alembic。为本库建立可重复初始化的版本标记与 schema 升级入口；数据库连接开启外键并在事务中写入完整书籍。
3. **01.3 本地验证基础**：在 `tests/research/` 放纯合成 fixture 和标准库 `unittest` 测试，覆盖默认参数、非法参数、Schema 唯一键、外键、事务回滚及包安装导入。将 DB、导出目录和本地缓存加入 `.gitignore`；测试不得提交小说正文、账号信息或真实页面缓存。

## 交付物

可安装的 `research` 包、可显示帮助的 CLI、独立研究库和最小离线测试。CLI 的未实现子命令需明确退出，不得假报采集成功。打包和数据库契约以 `contracts.md` 为准。

## 验收命令

在 Fork 根目录运行 `uv sync`、`uv run python -m research --help`、`uv build`、`uv run python -m unittest discover -s tests/research`、`uv run ruff check research tests/research`、`uv run ruff format --check research tests/research`。检查 wheel 列表确实含 `research/__main__.py`。若上游未带所需测试或导出依赖，在 `pyproject.toml` 中通过 uv 增加并锁定。

## 失败时处理

若 package discovery 与上游构建冲突，先保留可安装性和 CLI 验收，再调整 `research` 包位置与 `contracts.md`；不得只靠 `PYTHONPATH` 绕过。若 schema 改动会触及上游数据库，回到独立库方案。阶段 1 验收未过，榜单和 Source 任务不开始。
