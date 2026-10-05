---
name: automated-development
description: Use APD to route a software-development task across persistent Luna, Sol, and Astra Codex sessions for discovery, implementation, validation, and independent review.
---

Use this skill only when the user explicitly asks to use APD / automated multi-model development, or when the installed APD workflow is clearly the requested execution method.

APD is intentionally small. It is a local coordinator, not a native Codex subagent hierarchy.

## Preconditions

1. APD must be installed in the Python environment (`pip install -e <APD repo>`).
2. The target directory must already be a Git repository with at least one commit.
3. Existing Codex authentication is reused by the official `openai-codex` Python SDK.
4. The target project owns its own product rules. APD does not override repository instructions or user authorization.

## Run one routed step

```bash
apd run --repo "<repo>" --task "<task>"
```

The classifier maps the task to a logical model profile and permission mode.

## Run the minimal development loop

```bash
apd develop --repo "<repo>" --task "<objective>"
```

The loop is:

1. Luna discovery (read-only).
2. Astra deep reasoning only when discovery says it is genuinely needed (read-only).
3. Sol implementation (workspace-write).
4. Sol focused validation (read-only).
5. Astra review on a separate review thread (read-only).

APD does not commit, push, merge, deploy, or rewrite Git history.

## Evidence

After each turn, report the `[ROUTE]`, `[EXECUTION]`, and `[USAGE]` lines. Persistent state and receipts are stored under the target repository's Git metadata directory (`<git-dir>/apd/`), so APD does not add project files to the worktree.

If APD prints `APD_FAIL_CLOSED`, stop and report the exact blocker. Do not bypass a model, permission, repository, or state-version mismatch.
