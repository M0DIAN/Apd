# APD — 多模型自动开发协调器

APD 是一个给 Codex 用的轻量开发工具。它根据当前任务，在 Luna、Sol 和 Astra 之间选择模型，并保持各自的 Codex Session。开发过程仍是一条连续的主线，不需要手动来回切模型。

目前的默认分工：

| 任务 | 模型 | 权限 |
| --- | --- | --- |
| 查找代码、调用链、快速扫描 | Luna | 只读 |
| 写代码、修复问题 | Sol | 工作区写入 |
| 测试和验证 | Sol | 只读 |
| 复杂根因、架构分析 | Astra | 只读 |
| 独立复核 | Astra | 只读 |

APD 不是 Codex 原生的子 Agent 系统。它通过官方 `openai-codex` SDK 调度持久 Session，用本地状态记录进度。

## 安装

需要 Python 3.11 或更高版本：

```bash
git clone https://github.com/M0DIAN/apd.git
cd apd
python -m pip install -e .
```

APD 使用现有的 Codex 登录状态，不需要另外配置一套账号。

## 在 Codex 中使用

安装并启用 APD Skill 后，在项目中直接提出开发任务，例如：

> 修复导出页面偶尔崩溃的问题，并完成必要验证。

Codex 可以根据任务选择 APD，依次交给 Luna 发现、必要时 Astra 深度分析、Sol 实施和验证、Astra 独立复核。

也可以显式指定：

```text
$apd 修复这个问题并完成验证
```

Codex Skill 内部通过 `python -m apd` 调用 APD，不要求 `apd` console script 位于 PATH。手工和调试入口仍可使用 `apd ...`；找不到命令时，也可使用 `python -m apd ...`。

执行一次自动路由任务：

```bash
apd run --repo D:\GitHub\your-project --task "定位导出功能的调用链"
```

执行一轮开发流程：

```bash
apd develop --repo D:\GitHub\your-project --task "修复当前导出功能的问题"
```

流程通常是：发现 → 必要时深度分析 → 实施 → 验证 → 独立复核。

## 实时监控窗口

从 v0.2.0 开始，`apd run` 和 `apd develop` 默认打开独立监控窗口，`apd status` 不打开窗口。

窗口能看到当前任务和阶段、请求的模型、Router 原因、Session / Thread、权限、Canonical State 版本、仓库快照和最近的执行记录。

GUI 使用 PySide6 + QML，只读取本地状态，不参与 Router、Session 或 State Merge。窗口关闭或启动失败，APD 仍会继续运行。

不想打开 GUI：

```bash
apd develop --no-gui --repo D:\GitHub\your-project --task "..."
```

也可以设置环境变量 `APD_GUI=0`。手动打开窗口：

```bash
apd-gui --repo D:\GitHub\your-project
```

## 模型配置

配置在 `models.toml`：

```toml
[luna]
model = "gpt-6-luna"
effort = "high"

[sol]
model = "gpt-6.1-sol"
effort = "high"

[astra]
model = "gpt-6-astra"
effort = "high"
```

也可通过 `APD_MODELS` 或 `apd --models <models.toml> ...` 指定文件。APD 不会偷偷替换模型，调用失败时会报错并停止当前任务。

## 本地状态

每个项目的状态保存在 Git 元数据目录，不向项目工作区添加运行文件：

```text
<git-dir>/apd/
  state.json
  history.jsonl
  receipts.jsonl
  runtime.json
```

## 安全边界

只读任务改变了仓库，或状态版本不一致时，APD 会停止，不继续合并结果。

APD 本身不会自动执行 `commit`、`push`、`merge`、`reset`、`deploy` 或 `release`。这些操作仍由项目自己的开发规则和用户授权决定。

## Token 用量

GUI 和执行记录只显示当前运行时提供的 `usage`，不代表完整 Token 总量或最终账单。没有提供的数据会显示未知，APD 不会自行估算。

## 测试

```bash
python -m unittest discover -s tests -v
```

普通单元测试不会调用真实模型。
