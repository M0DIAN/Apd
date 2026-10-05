# APD — Automated Plugin Development

APD is a **minimal multi-model automatic development coordinator for Codex**.

It keeps one logical development mainline while routing work to persistent model profiles:

```text
Task
  ↓
TaskClassifier
  ↓
ModelRouter
  ↓
Session/Thread
 ┌──────────┬──────────┬──────────┐
 Luna       Sol        Astra
 discovery  implement  reason/review
 └──────────┴──────────┴──────────┘
  ↓
Structured result
  ↓
Canonical state merge
  ↓
Repository check
```

APD is **not** a native Codex subagent tree. It uses the official `openai-codex` Python SDK, which starts/resumes Codex threads and reuses existing Codex authentication.

## v0.1 scope

The first version deliberately contains only the minimum useful path:

- rule-based task classification;
- fixed model routing;
- persistent thread IDs;
- compact canonical state + delta history;
- read-only/workspace-write separation;
- structured JSON worker results;
- repository consistency checks;
- route receipts and raw SDK usage snapshots;
- a small `develop` loop.

It deliberately does **not** include a GUI, billing engine, database, event bus, fallback model chain, native subagents, custom broker, or deployment automation.

## Install

Python 3.11+:

```bash
git clone https://github.com/M0DIAN/Apd.git
cd Apd
python -m pip install -e .
```

The dependency `openai-codex` installs the matching official Codex runtime package. Existing Codex authentication is reused automatically.

## Configure models

Edit `models.toml`:

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

APD does not silently substitute a different logical profile. A failed model request fails the task.

## Single routed task

```bash
apd run --repo D:\GitHub\your-project --task "locate the call chain for the export action"
```

Or force a task type:

```bash
apd run --repo D:\GitHub\your-project --type REVIEW --task "review the current diff"
```

## Minimal automatic development loop

```bash
apd develop --repo D:\GitHub\your-project --task "fix the current export bug with the smallest sufficient change"
```

Current loop:

```text
DISCOVERY       → Luna  / READ_ONLY
(optional)
DEEP_REASONING  → Astra / READ_ONLY
IMPLEMENTATION  → Sol   / WORKSPACE_WRITE
TEST            → Sol   / READ_ONLY
REVIEW          → Astra / READ_ONLY (separate review thread)
```

The separate Astra review thread avoids treating an earlier Astra reasoning context as an independent review.

## Local state

APD writes state under the target repository's Git metadata directory:

```text
<git-dir>/apd/
  state.json
  history.jsonl
  receipts.jsonl
```

Nothing is added to the target worktree solely for APD state.

## Safety boundary

APD's built-in rules are intentionally small:

- read-only tasks fail if the repository changes during the turn;
- implementation is the only default workspace-write route;
- approval escalation is denied (`ApprovalMode.deny_all`);
- APD never requests full-access sandbox;
- stale state versions fail closed;
- APD does not commit, push, merge, reset, deploy, or release.

The target repository's own instructions and user authorization still govern what changes are allowed.

## Route evidence

A turn prints:

```text
[ROUTE] IMPLEMENTATION -> SOL reason=MAINLINE_IMPLEMENTATION permission=WORKSPACE_WRITE
[EXECUTION] model=gpt-6.1-sol thread=... resume=true
[USAGE] observed
```

`receipts.jsonl` records the requested model, thread ID, turn ID, route reason, permission mode, task status, and the SDK usage object when available.

`requested_model` is a request binding, not a claim about billing or a complete account-usage total.

## Tests

Pure local tests do not call a model:

```bash
python -m unittest discover -s tests -v
```

A real model E2E is intentionally not part of the unit suite because it consumes Codex usage and requires an authenticated account.

## Plugin files

APD includes:

- portable `plugin.json`;
- Codex compatibility manifest at `.codex-plugin/plugin.json`;
- `skills/automated-development/SKILL.md`.

The skill teaches Codex how to invoke the local APD coordinator. APD itself remains a normal Python program so its behavior is inspectable and testable.

## Non-goals for v0.1

Do not add these until real use proves a need:

- semantic/ML task classifier;
- generic agent framework;
- model fallback heuristics;
- supervisor dashboard;
- cost estimation;
- telemetry service;
- remote control plane;
- automatic Git commit/push/PR;
- production deployment.
