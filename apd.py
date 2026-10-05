from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

VERSION = "0.1.0"


class APDError(RuntimeError):
    pass


class TaskType(str, Enum):
    DISCOVERY = "DISCOVERY"
    IMPLEMENTATION = "IMPLEMENTATION"
    DEEP_REASONING = "DEEP_REASONING"
    REVIEW = "REVIEW"
    TEST = "TEST"
    GENERAL = "GENERAL"


class Permission(str, Enum):
    READ_ONLY = "READ_ONLY"
    WORKSPACE_WRITE = "WORKSPACE_WRITE"


@dataclass(frozen=True)
class Route:
    task_type: TaskType
    session: str
    reason: str
    permission: Permission

    @property
    def channel(self) -> str:
        if self.session == "sol" and self.permission == Permission.WORKSPACE_WRITE:
            return "sol:write"
        if self.task_type == TaskType.REVIEW:
            return "astra:review"
        return f"{self.session}:ro"


class TaskClassifier:
    RULES = (
        (TaskType.REVIEW, ("review", "audit", "复核", "审查")),
        (TaskType.IMPLEMENTATION, ("implement", "modify", "patch", "fix", "修改", "实现", "修复")),
        (TaskType.DEEP_REASONING, ("root cause", "architecture", "adversarial", "根因", "架构", "反证")),
        (TaskType.TEST, ("test", "validate", "verify", "测试", "验证")),
        (TaskType.DISCOVERY, ("find", "scan", "locate", "trace", "调用链", "定位", "扫描", "查找")),
    )

    def classify(self, text: str) -> TaskType:
        s = text.casefold()
        for task_type, words in self.RULES:
            if any(w.casefold() in s for w in words):
                return task_type
        return TaskType.GENERAL


class ModelRouter:
    TABLE = {
        TaskType.DISCOVERY: ("luna", "FAST_DISCOVERY", Permission.READ_ONLY),
        TaskType.IMPLEMENTATION: ("sol", "MAINLINE_IMPLEMENTATION", Permission.WORKSPACE_WRITE),
        TaskType.TEST: ("sol", "MAINLINE_TEST", Permission.READ_ONLY),
        TaskType.DEEP_REASONING: ("astra", "DEEP_REASONING", Permission.READ_ONLY),
        TaskType.REVIEW: ("astra", "FOCUSED_REVIEW", Permission.READ_ONLY),
        TaskType.GENERAL: ("sol", "GENERAL_MAINLINE", Permission.READ_ONLY),
    }

    def route(self, task_type: TaskType) -> Route:
        session, reason, permission = self.TABLE[task_type]
        return Route(task_type, session, reason, permission)


@dataclass(frozen=True)
class RepoSnapshot:
    head: str
    tree: str
    status: str
    diff_sha256: str


def run_git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if cp.returncode:
        raise APDError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout


def snapshot(repo: Path) -> RepoSnapshot:
    head = run_git(repo, "rev-parse", "HEAD").strip()
    tree = run_git(repo, "rev-parse", "HEAD^{tree}").strip()
    status = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    diff = run_git(repo, "diff", "--binary", "HEAD", "--").encode()
    return RepoSnapshot(head, tree, status, hashlib.sha256(diff).hexdigest())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


class StateStore:
    def __init__(self, repo: Path):
        git_dir = Path(run_git(repo, "rev-parse", "--git-dir").strip())
        if not git_dir.is_absolute():
            git_dir = (repo / git_dir).resolve()
        self.root = git_dir / "apd"
        self.state_path = self.root / "state.json"
        self.history_path = self.root / "history.jsonl"
        self.receipts_path = self.root / "receipts.jsonl"
        self.repo = repo

    def load(self) -> dict[str, Any]:
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if type(state.get("state_version")) is not int:
                raise APDError("invalid state.json")
            state.setdefault("sessions", {})
            state.setdefault("accepted_facts", [])
            return state
        s = snapshot(self.repo)
        state = {
            "schema_version": 1,
            "state_version": 0,
            "phase": "NEW",
            "current_task": "",
            "current_blocker": None,
            "next_action": "",
            "repository_head": s.head,
            "repository_tree": s.tree,
            "worktree_status": s.status,
            "worktree_diff_sha256": s.diff_sha256,
            "accepted_facts": [],
            "changed_files": [],
            "active_session": None,
            "sessions": {},
        }
        atomic_json(self.state_path, state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        atomic_json(self.state_path, state)

    def append_history(self, row: dict[str, Any]) -> None:
        append_jsonl(self.history_path, row)

    def append_receipt(self, row: dict[str, Any]) -> None:
        append_jsonl(self.receipts_path, row)

    def history_since(self, version: int) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows = [json.loads(x) for x in self.history_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if int(r.get("state_version", -1)) > version]


RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "FAIL", "BLOCKED"]},
        "summary": {"type": "string"},
        "accepted_facts": {"type": "array", "items": {"type": "string"}},
        "current_blocker": {"type": ["string", "null"]},
        "next_action": {"type": "string"},
        "needs_deep_reasoning": {"type": "boolean"},
    },
    "required": ["status", "summary", "accepted_facts", "current_blocker", "next_action", "needs_deep_reasoning"],
}


def parse_result(text: str | None) -> dict[str, Any]:
    if not text:
        raise APDError("worker returned no final response")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise APDError(f"worker returned invalid structured JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("status") not in {"PASS", "FAIL", "BLOCKED"}:
        raise APDError("worker result schema mismatch")
    for key in RESULT_SCHEMA["required"]:
        if key not in value:
            raise APDError(f"worker result missing {key}")
    return value


def load_models(path: Path) -> dict[str, dict[str, str]]:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    out = {}
    for name in ("luna", "sol", "astra"):
        row = raw.get(name)
        if not isinstance(row, dict) or not isinstance(row.get("model"), str):
            raise APDError(f"missing [{name}].model")
        out[name] = {"model": row["model"], "effort": str(row.get("effort", "high"))}
    return out


def usage_json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return str(value)


class Coordinator:
    def __init__(self, repo: Path, models_path: Path):
        self.repo = repo.resolve()
        self.models = load_models(models_path)
        self.store = StateStore(self.repo)
        self.classifier = TaskClassifier()
        self.router = ModelRouter()

    def _sdk(self):
        try:
            from openai_codex import ApprovalMode, Codex, Sandbox
        except ImportError as exc:
            raise APDError("openai-codex is not installed; run: pip install -e .") from exc
        return Codex, Sandbox, ApprovalMode

    def _state_context(self, state: dict[str, Any], channel: str) -> str:
        session = state.get("sessions", {}).get(channel, {})
        synced = int(session.get("synced_state_version", 0) or 0)
        compact = {
            "state_version": state["state_version"],
            "phase": state.get("phase"),
            "blocker": state.get("current_blocker"),
            "next_action": state.get("next_action"),
            "head": state.get("repository_head"),
            "tree": state.get("repository_tree"),
            "facts_tail": state.get("accepted_facts", [])[-12:],
            "delta": self.store.history_since(synced)[-20:],
        }
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    def _get_thread(self, codex, state: dict[str, Any], route: Route):
        Codex, Sandbox, ApprovalMode = self._sdk()
        sandbox = Sandbox.workspace_write if route.permission == Permission.WORKSPACE_WRITE else Sandbox.read_only
        row = state.setdefault("sessions", {}).setdefault(route.channel, {})
        model = self.models[route.session]["model"]
        thread_id = row.get("thread_id")
        if thread_id:
            thread = codex.thread_resume(
                thread_id,
                approval_mode=ApprovalMode.deny_all,
                cwd=str(self.repo),
                include_turns=False,
                model=model,
                sandbox=sandbox,
            )
            resumed = True
        else:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(self.repo),
                model=model,
                sandbox=sandbox,
            )
            row["thread_id"] = thread.id
            row["synced_state_version"] = state["state_version"]
            resumed = False
        return thread, sandbox, resumed

    def _prompt(self, objective: str, route: Route, state_context: str, extra: str) -> str:
        write_rule = (
            "You may modify repository working-tree files. Do not commit, push, reset, rewrite history, or touch files outside the repo. Make the smallest sufficient change."
            if route.permission == Permission.WORKSPACE_WRITE
            else "Read-only task. Do not modify repository files."
        )
        role = {
            TaskType.DISCOVERY: "Locate the relevant code and the minimum path forward.",
            TaskType.IMPLEMENTATION: "Implement the smallest sufficient change.",
            TaskType.DEEP_REASONING: "Analyze root cause, architecture, and counter-evidence; do not implement.",
            TaskType.REVIEW: "Independently review the current candidate/diff; do not implement.",
            TaskType.TEST: "Run or inspect focused validation; do not alter source files.",
            TaskType.GENERAL: "Handle the task directly and conservatively.",
        }[route.task_type]
        return f"""You are the APD {route.session} worker.
Objective: {objective}
Task type: {route.task_type.value}
Permission: {route.permission.value}
{write_rule}
Role: {role}

Canonical state/delta:
{state_context}

Additional context:
{extra or "(none)"}

Return only JSON matching the requested output schema.
"""

    def run_step(self, codex, objective: str, task_type: TaskType, extra: str = "") -> dict[str, Any]:
        Codex, Sandbox, ApprovalMode = self._sdk()
        route = self.router.route(task_type)
        state = self.store.load()
        base_version = int(state["state_version"])
        before = snapshot(self.repo)
        thread, sandbox, resumed = self._get_thread(codex, state, route)
        model = self.models[route.session]["model"]
        result = thread.run(
            self._prompt(objective, route, self._state_context(state, route.channel), extra),
            approval_mode=ApprovalMode.deny_all,
            cwd=str(self.repo),
            effort=self.models[route.session]["effort"],
            model=model,
            output_schema=RESULT_SCHEMA,
            sandbox=sandbox,
        )
        worker = parse_result(result.final_response)
        after = snapshot(self.repo)

        if route.permission == Permission.READ_ONLY and after != before:
            raise APDError("READ_ONLY_REPOSITORY_CHANGED")

        current = self.store.load()
        if int(current["state_version"]) != base_version:
            raise APDError("STATE_VERSION_MISMATCH")

        current["state_version"] = base_version + 1
        current["phase"] = task_type.value
        current["current_task"] = objective
        current["current_blocker"] = worker["current_blocker"]
        current["next_action"] = worker["next_action"]
        current["repository_head"] = after.head
        current["repository_tree"] = after.tree
        current["worktree_status"] = after.status
        current["worktree_diff_sha256"] = after.diff_sha256
        current["changed_files"] = [x[3:].strip() for x in after.status.splitlines() if len(x) >= 4]
        current["active_session"] = route.session
        for fact in worker["accepted_facts"]:
            if isinstance(fact, str) and fact and fact not in current["accepted_facts"]:
                current["accepted_facts"].append(fact)
        row = current["sessions"].setdefault(route.channel, {})
        row["thread_id"] = thread.id
        row["synced_state_version"] = current["state_version"]
        row["status"] = "HOT"

        history = {
            "state_version": current["state_version"],
            "task_type": task_type.value,
            "summary": worker["summary"],
            "current_blocker": worker["current_blocker"],
            "next_action": worker["next_action"],
            "changed_files": current["changed_files"],
        }
        receipt = {
            "state_version": current["state_version"],
            "task_type": task_type.value,
            "router_selected_session": route.session,
            "router_reason": route.reason,
            "permission_mode": route.permission.value,
            "requested_model": model,
            "thread_id": thread.id,
            "turn_id": result.id,
            "session_resumed": resumed,
            "task_status": worker["status"],
            "usage": usage_json(result.usage),
        }
        self.store.append_history(history)
        self.store.append_receipt(receipt)
        self.store.save(current)

        print(f"[ROUTE] {task_type.value} -> {route.session.upper()} reason={route.reason} permission={route.permission.value}")
        print(f"[EXECUTION] model={model} thread={thread.id[:8]}... resume={str(resumed).lower()}")
        print("[USAGE] observed" if result.usage is not None else "[USAGE] UNKNOWN_NOT_EXPOSED")
        return {"result": worker, "receipt": receipt, "state": current}

    def develop(self, objective: str) -> int:
        Codex, _, _ = self._sdk()
        with Codex() as codex:
            d = self.run_step(codex, f"Discover the minimum implementation path for: {objective}", TaskType.DISCOVERY)
            if d["result"]["status"] != "PASS":
                return 2
            context = "Discovery:\n" + d["result"]["summary"]
            if d["result"]["needs_deep_reasoning"]:
                a = self.run_step(codex, f"Resolve the difficult design/root-cause questions for: {objective}", TaskType.DEEP_REASONING, context)
                if a["result"]["status"] != "PASS":
                    return 2
                context += "\n\nDeep reasoning:\n" + a["result"]["summary"]
            i = self.run_step(codex, objective, TaskType.IMPLEMENTATION, context)
            if i["result"]["status"] != "PASS":
                return 2
            t = self.run_step(codex, f"Validate the current implementation for: {objective}", TaskType.TEST, "Implementation:\n" + i["result"]["summary"])
            if t["result"]["status"] != "PASS":
                return 2
            r = self.run_step(codex, f"Independently review the current candidate for: {objective}", TaskType.REVIEW)
            return 0 if r["result"]["status"] == "PASS" else 2


def default_models() -> Path:
    return Path(os.environ.get("APD_MODELS", Path(__file__).resolve().with_name("models.toml")))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="apd", description="Minimal multi-model automated development coordinator")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--models", default=str(default_models()))
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status")
    s.add_argument("--repo", default=".")

    r = sub.add_parser("run")
    r.add_argument("--repo", default=".")
    r.add_argument("--task", required=True)
    r.add_argument("--type", default="AUTO", choices=["AUTO"] + [x.value for x in TaskType])

    d = sub.add_parser("develop")
    d.add_argument("--repo", default=".")
    d.add_argument("--task", required=True)

    args = p.parse_args(argv)
    try:
        c = Coordinator(Path(args.repo), Path(args.models))
        if args.cmd == "status":
            print(json.dumps(c.store.load(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.cmd == "develop":
            return c.develop(args.task)
        task_type = c.classifier.classify(args.task) if args.type == "AUTO" else TaskType(args.type)
        Codex, _, _ = c._sdk()
        with Codex() as codex:
            out = c.run_step(codex, args.task, task_type)
        print(json.dumps(out["result"], ensure_ascii=False, indent=2))
        return 0 if out["result"]["status"] == "PASS" else 2
    except (APDError, RuntimeError) as exc:
        print(f"APD_FAIL_CLOSED: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("APD_INTERRUPTED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
