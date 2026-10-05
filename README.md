# APD — 多模型自动开发协调器

APD 是一个面向 Codex 的轻量多模型自动开发协调器。它维持一个逻辑开发主线，根据任务类型自动路由 Luna、Sol、Astra，并通过持久 Codex Session、Canonical State、权限隔离、State Merge 和 Repository Check 保持连续开发。

APD 使用官方 `openai-codex` Python SDK 启动与恢复 Codex thread，复用现有 Codex 认证。它不是原生 Codex subagent 树。

```text
任务 → TaskClassifier → ModelRouter → 持久 Session
                                      │
                         Luna / Sol / Astra
                                      │
                         结构化结果 → State Merge
                                      │
                              Repository Check
                                      │
                <git-dir>/apd/runtime.json → 独立只读 GUI
```

## 安装

需要 Python 3.11+：

```bash
git clone https://github.com/M0DIAN/Apd.git
cd Apd
python -m pip install -e .
```

依赖保持为 `openai-codex` 与 `PySide6`。前者安装官方 Codex runtime，后者提供 Qt Quick 桌面窗口。

## 配置模型

编辑 `models.toml`：

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

也可用 `APD_MODELS` 或 `apd --models <models.toml> ...` 指定配置文件。APD 不会静默替换模型，模型请求失败时任务失败。

## 单次路由任务

```bash
apd run --repo D:\GitHub\your-project --task "locate the call chain for the export action"
apd run --repo D:\GitHub\your-project --type REVIEW --task "review the current diff"
```

## 最小自动开发循环

```bash
apd develop --repo D:\GitHub\your-project --task "fix the current export bug with the smallest sufficient change"
```

| 任务类型 | Session | 权限 |
| --- | --- | --- |
| `DISCOVERY` / 发现 | Luna | `READ_ONLY` |
| `DEEP_REASONING` / 深度分析（按需） | Astra | `READ_ONLY` |
| `IMPLEMENTATION` / 实施 | Sol | `WORKSPACE_WRITE` |
| `TEST` / 验证 | Sol | `READ_ONLY` |
| `REVIEW` / 独立复核 | Astra 的独立 review thread | `READ_ONLY` |
| `GENERAL` / 常规任务 | Sol | `READ_ONLY` |

独立 review thread 避免将先前分析上下文当作独立复核。

## 实时监控 GUI

`apd run` 与 `apd develop` 默认自动启动 **APD 多模型开发监视器**，`apd status` 不启动窗口。

窗口是独立的 PySide6 + QML 进程，每 400 ms 读取本地状态。它显示当前路由、请求模型 ID、Session、权限、Canonical State、仓库快照、最近 20 条事件和实际可观测用量。仓库状态是 Core 最近发布的快照，GUI 不自行监测工作区变动。

```bash
apd develop --no-gui --repo D:\GitHub\your-project --task "fix the current export bug"
apd run --no-gui --repo D:\GitHub\your-project --task "locate the export action"
```

也可设置环境变量 `APD_GUI=0`：

```powershell
$env:APD_GUI = "0"
```

手动打开观察窗口：

```bash
apd-gui --repo D:\GitHub\your-project
python -m apd_gui --repo D:\GitHub\your-project
```

QML 随 `apd_ui` 资源包安装，使用 `importlib.resources` 定位；editable 安装与普通 wheel 安装均不依赖当前目录。Windows 优先使用 `pythonw.exe`，否则使用当前 Python。Core 不等待 GUI；窗口关闭、崩溃、PySide6 缺失或 QML 加载失败均不影响开发任务。Core 退出后，窗口可以继续显示最终状态。

GUI 没有执行控制按钮，只读取状态文件。它不调用 Codex、Router，不修改 Session、权限或目标仓库。

## 本地状态与隐私

所有状态放在目标仓库的 Git 元数据目录中，兼容 Git worktree：

```text
<git-dir>/apd/
  state.json
  history.jsonl
  receipts.jsonl
  runtime.json
```

`state.json` 是已有 Canonical State；`history.jsonl` 和 `receipts.jsonl` 保存步骤历史与执行记录。`runtime.json` 用原有 atomic write 更新，只代表当前阶段：

`IDLE`、`STARTING`、`ROUTING`、`SYNCING`、`MODEL_RUNNING`、`MERGING`、`VALIDATING`、`REVIEWING`、`COMPLETED`、`FAILED`。

runtime 的任务摘要最多保留首行 160 字符；命中凭据关键词、URL 内嵌账号、配置赋值、代码、盘符/UNC 路径或独立 POSIX 绝对路径时会隐藏，多行正文不会复制。它不保存完整 worker prompt、模型回复、原始异常、认证内容或环境变量。GUI 的 blocker 与 next action 从已有 Canonical State 读取；错误只记录稳定短码与受控描述。

JSON 暂时不可读时，窗口保留上次有效状态并显示“等待状态更新”。监控状态写入失败只警告，不改变 Core 的任务结果。

## 用量与机器协议

CLI 保持原有机器协议：

```text
[ROUTE] IMPLEMENTATION -> SOL reason=MAINLINE_IMPLEMENTATION permission=WORKSPACE_WRITE
[EXECUTION] model=gpt-6.1-sol thread=... resume=true
[USAGE] observed
```

`receipts.jsonl` 记录请求模型、thread ID、turn ID、路由原因、权限、任务状态和 SDK 实际提供的 usage。`requested_model` 表示请求绑定，不代表计费证明。

GUI 仅显示 receipt 中实际存在的 Input、Cached Input、Output、Reasoning 计数。当前 turn 未提供用量时显示“当前运行时未提供完整用量信息”，不沿用其他 turn 的计数，也不估算 Token、金额或 ChatGPT 额度。

**仅显示当前运行时提供的可观测计数，不代表完整 Token 总量或最终账单。**

## 安全边界

- 只有实施路由默认允许工作区写入；只读任务期间仓库变化时 fail closed。
- 审批升级被拒绝（`ApprovalMode.deny_all`），不请求 full-access sandbox。
- 旧 state version 拒绝合并；worker 异常仍使用 `APD_FAIL_CLOSED`。
- APD 不自动 commit、push、merge、reset、deploy 或 release。
- 目标项目的规则和用户授权继续生效。

## 验证

```bash
python -m unittest discover -s tests -v
python -m compileall apd.py apd_gui.py
git diff --check
apd --version
apd-gui --help
apd --help
```

原有 6 项测试保留。新增测试覆盖 runtime、GUI 旁路、文件读取容错、中文映射、真实 offscreen QML 加载和普通安装后的资源定位。测试不调用模型；GUI 验证无需消耗模型额度。

## Plugin 与 Skill

包含 `plugin.json`、`.codex-plugin/plugin.json` 和 `skills/automated-development/SKILL.md`。用户可见介绍以中文为主，enum、CLI 命令与机器协议保留英文。

v0.2 继续保持最小实现：没有 GUI 控制器体系、IPC 服务、HTTP/WebSocket、数据库、远程遥测、billing 或 Supervisor 控制功能。
