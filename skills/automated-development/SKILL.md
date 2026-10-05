---
name: automated-development
description: 使用 APD 在持久 Luna、Sol、Astra Codex Session 之间路由开发任务，完成发现、实施、验证与独立复核，并通过独立只读 GUI 实时观察。
---

仅在用户明确要求使用 APD / 自动多模型开发，或已安装 APD 工作流且用户明确要求以此执行时使用。

APD 是小型本地协调器，不是原生 Codex subagent 树。

## 前提

1. Python 环境已安装 APD（`pip install -e <APD repo>`）。
2. 目标目录是已有至少一个 commit 的 Git 仓库。
3. 官方 `openai-codex` Python SDK 复用现有 Codex 认证。
4. 目标项目保留自己的产品规则，APD 不覆盖仓库指令或用户授权。

## 单次路由

```bash
apd run --repo "<repo>" --task "<task>"
apd run --repo "<repo>" --type REVIEW --task "<task>"
```

TaskClassifier 选择任务类型，ModelRouter 绑定逻辑模型与权限。

## 最小开发循环

```bash
apd develop --repo "<repo>" --task "<objective>"
```

1. Luna：`DISCOVERY` / 发现，`READ_ONLY`。
2. 按需 Astra：`DEEP_REASONING` / 深度分析，`READ_ONLY`。
3. Sol：`IMPLEMENTATION` / 实施，`WORKSPACE_WRITE`。
4. Sol：`TEST` / 验证，`READ_ONLY`。
5. Astra 独立 review thread：`REVIEW` / 独立复核，`READ_ONLY`。

## 实时监控

`apd run` 和 `apd develop` 默认打开独立 PySide6/QML 监控窗口。GUI 每 400 ms 只读 `<git-dir>/apd/` 中的本地状态，没有模型控制按钮；关闭或启动失败不会中断 Core。`apd status` 不自动打开 GUI。

关闭自动 GUI：

```bash
apd develop --no-gui --repo "<repo>" --task "<objective>"
apd run --no-gui --repo "<repo>" --task "<task>"
```

也可设置 `APD_GUI=0`。手动观察：

```bash
apd-gui --repo "<repo>"
python -m apd_gui --repo "<repo>"
```

GUI 用量只显示 runtime 实际提供的可观测计数，不代表完整 Token 总量或最终账单。

## 执行证据与失败处理

每次运行后报告 `[ROUTE]`、`[EXECUTION]` 和 `[USAGE]`。状态与执行记录保存在 Git 元数据目录的 `state.json`、`history.jsonl`、`receipts.jsonl`；实时观察状态写入 `runtime.json`，不向目标工作区添加运行文件。

APD 不自动 commit、push、merge、deploy 或重写 Git 历史。

若出现 `APD_FAIL_CLOSED`，停止并报告具体 blocker，不绕过模型、权限、仓库或 state version 不一致。`APD_GUI_WARNING` 只表示旁路监控失败，不应被当作 Core 失败。
