# 阶段 0：Fork 与技术可行性

## 输入与前置条件

读取 [产品说明书](../../网文开篇研究采集器-产品说明书.md)及 [开发契约](contracts.md)。当前目录已接入 Fork；本阶段核对榜单结构、上游接口和真实 Source 请求链路。

## 具体任务

1. **00.1 Fork 基线**：在 GitHub Fork `lncrawl/lightnovel-crawler`，以其当前默认 `dev` 为基线，在现有目录接入 Fork 和 `upstream` 远端；切出 `feature/research-pipeline`。记录上游提交 SHA、Fork URL、Python/uv 版本、安装与既有 CLI 的运行结果。保留当前两份文档及 `docs/plan/`，确认 Git checkout 不覆盖它们。
2. **00.2 榜单证据**：核实「签约新书榜」当前官方入口、榜单名、分页、原始名次、书籍 ID、书籍 URL 和更新提示。人工抽查少量作品目录，记录可见章节与免费标识；不以检索结果或旧页面当作当前页面结构。若榜单不能稳定给出书籍 ID 与原始名次，记录阻断。
3. **00.3 上游接缝**：读取 Fork 中 `AGENTS.md`、相关 `.claude/skills/add-source`、`lncrawl/app.py`、Source 注册与抓取路径、`pyproject.toml`。记录 Research CLI 如何调用上游 Source、是否需改 `sources/`、`research*` 如何纳入安装包、上游 CLI/DB 哪些部分不复用。先找类似 Source；不得凭旧版 API 设计适配。
4. **00.4 正文链路**：用起点 Source 请求一本候选书的详情页、目录和首个公开免费章节；记录渲染方式、正文选择器、文本解析结果及失败原因。正文只在内存中核验，不提交章节正文、账号信息或页面缓存。

## 交付物

在本文件末尾的“核验记录”填写结果；将接口决策同步到 `contracts.md`。Fork 与上游远端、基线 SHA、榜单官方 URL、样本目录、Source 调用链和首章请求结果必须可复查。无需把章节正文、账号信息或页面缓存提交到仓库。

## 验收命令与人工核验

Fork 就绪后在 PowerShell 执行 `git remote -v`、`git rev-parse HEAD`、`uv sync`、`uv run python -m lncrawl --help`。上游源码检查使用 `uv run python -m lncrawl dev check-sources`；`make check-sources` 是站点可达性探测，不作为代码验证。人工打开官方榜单与少量书籍页面，核对 00.2 的字段与 00.4 的依据。任何环境命令失败，先分类为安装、网络、上游基线或本地配置问题。

## 失败处理

无 Fork 权限或上游代码不可用时，保持本地文档和调查结果，阶段 1 不开始。榜单入口不稳定时记录实测 URL 与失败样本，修订可行性结论。站点明确要求登录、付费、验证码或拒绝访问时停止该样本，记录 `blocked_access`。

## 核验记录（执行阶段填写）

| 项目 | 结果与证据 |
| --- | --- |
| 核验日期与执行者 | 2026-09-24，Codex；用独立 Chromium 低频读取榜单、一本书页及一章公开页，后续均用本地缓存离线核对 |
| Fork URL、上游 SHA | [sehor/lightnovel-crawler](https://github.com/sehor/lightnovel-crawler)，`dev` 基线 `59b0382d51927953aa8120c5de62dab23ce3f731`；本地分支 `feature/research-pipeline` |
| 环境基线 | Windows、`uv 0.11.19`；`uv sync --frozen` 与 `uv run --no-sync python -m lncrawl --help` 通过；源码检查加载 446 个 crawler，与索引一致 |
| 榜单官方 URL、分页与名次 | [签约新书榜](https://www.qidian.com/rank/signNewBkAll/)页面标题为「签约新书榜」，每页 20 条；页面展示到第 25 页的分页链接；2026-09-25 已实测首页和第二页。`li[data-rid]` 为每页 1—20，`.rank-tag` 展示跨页名次，第二页首项为 21。书籍链接为 https://www.qidian.com/book/{id}/。入选作品无需额外核验作者是否新人 |
| Source 接缝与打包方式 | `ctx.sources.init_crawler(url)` 初始化 Source；`lncrawl/core/template.py` 为新 Source 基类；`pyproject.toml` 已包含 `research*`，本地 wheel 构建成功；新增的起点 Source 可解析 `qidian.com` |
| 榜单元数据实测 | 2026-09-25 使用共享 Scraper 获取榜单前两页，冻结 21 条候选记录；榜单名次、书籍 ID、书名、作者和分类均已落库验证 |
| 章节正文实测 | 2026-09-25 默认批次扫描 12 个候选，成功保存 8 本、每本 5 章；第 12 个候选显示验证码后停止，运行标记 `blocked_access`。成功部分已导出 JSONL 与 Parquet |
| 技术结论 | 榜单前两页、Source 目录和首章正文链路已实测；继续实现筛选、原子保存与续跑 |
