---
name: apd
description: Use APD for multi-step software development in a local Git repository to investigate and fix a bug, implement or refactor code, add a feature, validate a change, or independently review a candidate. Keep one development mainline while routing discovery to Luna, implementation and tests to Sol, and deep reasoning or independent review to Astra. Do not invoke APD from an APD internal worker session.
---

先检查当前环境：如果 `APD_INTERNAL_WORKER=1`，不要调用 APD Skill、APD CLI（包括 `python -m apd develop`、`python -m apd run`）或启动 GUI；直接执行当前 Worker 被分配的任务。

## 项目与前提

APD 适用于本地 Git 项目的开发、调查、验证和复核；普通知识问答无需调用。保留目标项目的仓库指令和用户授权边界。

在当前项目目录执行 `git rev-parse --show-toplevel`，取得 Git root，再用 `git rev-parse --verify HEAD` 确认已有 commit。若不属于 Git 仓库，说明“APD需要在已有Git项目中运行”；若尚无 commit，停止并说明。不要代为初始化或创建提交。

使用已安装 APD 的 Python 环境（在 APD 仓库中执行 `python -m pip install -e .`），先用 `python -m apd --version` 确认模块可运行，并有可用的 Codex 登录状态。不要求 `apd` 或 `apd-gui` 位于 PATH；若模块不可用，报告缺少的前提，不自行改用户的全局配置。

## 选择并调用

修复、实现、增加功能、解决测试失败、重构等开发目标，默认调用完整流程：

```bash
python -m apd develop --repo "<git-root>" --task "<用户目标>"
```

任务文本作为一个参数传入，按当前 shell 正确转义，不把用户内容拼成可执行代码。

流程为 `DISCOVERY`（Luna）→ 按需 `DEEP_REASONING`（Astra）→ `IMPLEMENTATION`（Sol）→ `TEST`（Sol）→ `REVIEW`（Astra 独立复核）。只有实施阶段使用 `WORKSPACE_WRITE`，其他阶段使用 `READ_ONLY`。

用户明确只要单步时，使用 `python -m apd run --repo "<git-root>" --type <TYPE> --task "<用户目标>"`：

| 用户要求 | TYPE |
| --- | --- |
| 只查找、定位、扫描或调查 | DISCOVERY |
| 只验证现有候选 | TEST |
| 只独立复核、审查 | REVIEW |
| 明确只实施、不要验证 | IMPLEMENTATION |

通常的实施请求仍用 `develop`。保留默认自动 GUI，仅当用户明确不要 GUI 或环境明显 headless 时加 `--no-gui`。GUI 关闭或 `APD_GUI_WARNING` 不影响 Core；`APD_FAIL_CLOSED` 则停止并报告 blocker，不绕过检查或自动重试。

`develop` / `run` 已负责自动启动 GUI，正常流程不要额外启动第二个窗口。用户只想手动观察时，可使用 `python -m apd_gui --repo "<git-root>"`。

## 等待并返回结果

外层 Codex 理解目标、调用 APD、等待结束并解释结果。不要在 APD 后重复实施同一个任务；APD 不自动 commit、push、merge、reset、deploy 或 release。

结合退出码、`[ROUTE]`、`[EXECUTION]`、`[USAGE]` 和 `python -m apd status --repo "<git-root>"` 核对本次结果。若需要阶段或复核详情，只读取 Git 元数据目录 `<git-dir>/apd/` 中本次运行相关的状态和记录，不把旧运行当作本次成功证据。

简洁报告 `APD RESULT`、最终 `PASS` / `FAIL` / `BLOCKED`、实际完成的阶段、修改文件、验证和独立复核结果，以及 blocker。未完成的阶段明确说明；不要倾倒完整 `runtime.json`、`history.jsonl` 或 `receipts.jsonl`。
