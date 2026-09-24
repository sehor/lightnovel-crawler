# 阶段 0：Fork、可行性与权限关口

## 输入与前置条件

读取 [产品说明书](../../网文开篇研究采集器-产品说明书.md)及 [开发契约](contracts.md)。当前目录已接入 Fork；本阶段继续核实榜单与访问方式。正文批量采集必须等待关口结论。

## 具体任务

1. **00.1 Fork 基线**：在 GitHub Fork `lncrawl/lightnovel-crawler`，以其当前默认 `dev` 为基线，在现有目录接入 Fork 和 `upstream` 远端；切出 `feature/research-pipeline`。记录上游提交 SHA、Fork URL、Python/uv 版本、安装与既有 CLI 的运行结果。保留当前两份文档及 `docs/plan/`，确认 Git checkout 不覆盖它们。
2. **00.2 榜单证据**：核实「新人·签约新书榜」当前官方入口、榜单名、分页、原始名次、书籍 ID、书籍 URL 和更新提示。人工抽查少量作品目录，记录可见章节与免费标识；不以检索结果或旧页面当作当前页面结构。若榜单不能稳定给出书籍 ID 与原始名次，记录阻断。
3. **00.3 上游接缝**：读取 Fork 中 `AGENTS.md`、相关 `.claude/skills/add-source`、`lncrawl/app.py`、Source 注册与抓取路径、`pyproject.toml`。记录 Research CLI 如何调用上游 Source、是否需改 `sources/`、`research*` 如何纳入安装包、上游 CLI/DB 哪些部分不复用。先找类似 Source；不得凭旧版 API 设计适配。
4. **00.4 权限关口**：核验当前适用的起点协议、站点访问规则及可用的官方或获许可方式，分别记录榜单元数据与章节正文的依据、日期和链接。结论只能是 `GO`（有明确可用方式）或 `BLOCKED`（禁止或无法确认）。`BLOCKED` 时后续仅能进行本地模拟、文档和可验证的元数据工作，停止正文采集实现；不把人工可读或“免费”当成自动采集授权。

## 交付物

在本文件末尾的“核验记录”填写结果；将接口决策同步到 `contracts.md`。Fork 与上游远端、基线 SHA、榜单官方 URL、样本目录、访问规则证据及 `GO/BLOCKED` 结论必须可复查。无需把章节正文、账号信息或页面缓存提交到仓库。

## 验收命令与人工核验

Fork 就绪后在 PowerShell 执行 `git remote -v`、`git rev-parse HEAD`、`uv sync`、`uv run python -m lncrawl --help`。上游源码检查使用 `uv run python -m lncrawl dev check-sources`；`make check-sources` 是站点可达性探测，不作为代码验证。人工打开官方榜单与少量书籍页面，核对 00.2 的字段与 00.4 的依据。任何环境命令失败，先分类为安装、网络、上游基线或本地配置问题。

## 失败与关口处理

无 Fork 权限或上游代码不可用时，保持本地文档和调查结果，阶段 1 不开始。榜单入口不稳定时记录实测 URL 与失败样本，修订可行性结论。正文规则或允许方式不明确时结论为 `BLOCKED`；不以技术手段绕过，也不让阶段 3—5 的正文任务进入执行队列。

## 核验记录（执行阶段填写）

| 项目 | 结果与证据 |
| --- | --- |
| 核验日期与执行者 | 2026-09-24，Codex；榜单入口仍需核对 |
| Fork URL、上游 SHA | [sehor/lightnovel-crawler](https://github.com/sehor/lightnovel-crawler)，`dev` 基线 `59b0382d51927953aa8120c5de62dab23ce3f731`；本地分支 `feature/research-pipeline` |
| 环境基线 | Windows、`uv 0.11.19`；`uv sync --frozen` 与 `uv run --no-sync python -m lncrawl --help` 通过；源码检查加载 446 个 crawler，与索引一致 |
| 榜单官方 URL、分页与名次 | [起点首页](https://www.qidian.com/)展示「新人·签约新书榜」；专页 URL、分页及完整名次尚待人工核对 |
| Source 接缝与打包方式 | `ctx.sources.init_crawler(url)` 初始化 Source；`lncrawl/core/template.py` 为新 Source 基类；`pyproject.toml` 当前仅打包 `lncrawl*` 和 `sources*`。现有同名 Source 指向 `idqidian.us`、`qidianunderground.org`，不支持 `qidian.com` |
| 榜单元数据访问依据 | 尚未确认允许的自动读取方式；只完成公开页面的人工调查 |
| 章节正文访问依据 | [起点用户服务协议](https://acts.qidian.com/pact/userpact20220316.html)覆盖起点中文网，要求按平台提供或认可的方式使用；未找到明确允许自动批量保存正文的方式或授权 |
| 关口结论 `GO/BLOCKED` | `BLOCKED`：正文采集访问方式无法确认；阶段 3—5 不启动。若取得明确允许方式或授权，复核证据后再改为 `GO` |

起点 [用户服务协议](https://acts.qidian.com/pact/userpact20220316.html)和上游 [AGENTS.md](https://github.com/lncrawl/lightnovel-crawler/blob/dev/AGENTS.md)是本阶段的起始材料，执行时还须核对其是否仍为适用版本。
