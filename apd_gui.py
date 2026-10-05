from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

USAGE_NOTICE = "仅显示当前运行时提供的可观测计数，不代表完整 Token 总量或最终账单。"
USAGE_UNAVAILABLE = "当前运行时未提供完整用量信息"
LABELS = {
    "DISCOVERY": "发现", "IMPLEMENTATION": "实施", "DEEP_REASONING": "深度分析",
    "TEST": "验证", "REVIEW": "独立复核", "GENERAL": "常规任务",
    "READ_ONLY": "只读", "WORKSPACE_WRITE": "工作区写入",
    "PASS": "通过", "FAIL": "失败", "BLOCKED": "阻塞",
    "IDLE": "待命", "STARTING": "正在启动", "ROUTING": "正在路由",
    "SYNCING": "正在同步 Session", "MODEL_RUNNING": "模型执行中",
    "MERGING": "正在合并状态", "VALIDATING": "正在验证", "REVIEWING": "正在独立复核",
    "RUNNING": "正在运行", "COMPLETED": "已完成", "FAILED": "失败",
}
ACTIVE_STATUSES = {"STARTING", "ROUTING", "SYNCING", "MODEL_RUNNING", "MERGING", "VALIDATING", "REVIEWING"}


def load_json_safe(path: Path, fallback: Any = None) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, ValueError, UnicodeError):
        return fallback


def tail_jsonl_safe(path: Path, limit: int = 20, fallback: Any = None) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        # Read a bounded tail, not the entire lifetime event log.
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 65536))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except ValueError:
                continue
        return rows[-limit:]
    except OSError:
        return fallback if isinstance(fallback, list) else []


def short_id(value: Any, width: int = 4) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    return value if len(value) <= width * 2 + 3 else f"{value[:width]}...{value[-width:]}"


def translate_status(value: Any) -> str:
    return LABELS.get(value, value) if isinstance(value, str) else "—"


def format_usage(usage: Any) -> dict[str, Any]:
    out = {"input": "—", "cached": "—", "output": "—", "reasoning": "—", "available": False}
    if isinstance(usage, dict):
        keys = {
            "input": ("input_tokens", "inputTokens"),
            "cached": ("cached_input_tokens", "cachedInputTokens"),
            "output": ("output_tokens", "outputTokens"),
            "reasoning": ("reasoning_tokens", "reasoningTokens"),
        }
        for label, alternatives in keys.items():
            value = next((usage[key] for key in alternatives if key in usage), None)
            if value is None and label in {"cached", "reasoning"}:
                details = usage.get("input_tokens_details" if label == "cached" else "output_tokens_details", {})
                if isinstance(details, dict):
                    value = details.get("cached_tokens" if label == "cached" else "reasoning_tokens")
            if type(value) is int and value >= 0:
                out[label] = f"{value:,}"
                out["available"] = True
    out["message"] = "可观测 Token Usage" if out["available"] else USAGE_UNAVAILABLE
    out["notice"] = USAGE_NOTICE
    return out


def read_observation(root: Path, previous: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    raw = dict(previous)
    runtime = load_json_safe(root / "runtime.json")
    waiting = runtime is None
    if runtime is not None:
        raw["runtime"] = runtime
    state = load_json_safe(root / "state.json")
    if state is not None:
        raw["state"] = state
    elif (root / "state.json").exists():
        waiting = True
    for name in ("history", "receipts"):
        raw[name] = tail_jsonl_safe(root / f"{name}.jsonl", fallback=raw.get(name, []))
    return raw, waiting


def _text(value: Any, default: str = "—") -> str:
    return str(value) if isinstance(value, (str, int)) and str(value) else default


def _time(value: Any) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "—"


def observation_view(raw: dict[str, Any], waiting: bool) -> dict[str, Any]:
    runtime = raw.get("runtime", {})
    state = raw.get("state", {})
    receipts = raw.get("receipts", [])
    status = runtime.get("status", "IDLE")
    active = status in ACTIVE_STATUSES if isinstance(status, str) else False
    selected = runtime.get("router_selected_session", state.get("active_session"))
    models = runtime.get("models", {})
    models = models if isinstance(models, dict) else {}
    cards = []
    for name, role in (("luna", "发现"), ("sol", "实施 / 验证"), ("astra", "深度分析 / 独立复核")):
        last = next((r for r in reversed(receipts) if r.get("router_selected_session") == name), {})
        is_active = active and selected == name
        cards.append({"name": name.title(), "role": role, "active": is_active,
                      "model": _text(runtime.get("model") if is_active else last.get("requested_model", models.get(name)), "等待模型信息"),
                      "status": "工作中" if is_active else "待命"})
    by_version = {}
    for row in raw.get("history", []):
        version = row.get("state_version")
        if type(version) is int:
            by_version[version] = dict(row)
    for row in receipts:
        version = row.get("state_version")
        if type(version) is int:
            by_version.setdefault(version, {}).update(row)
    events = [{"time": _time(row.get("updated_at")),
               "session": _text(row.get("router_selected_session"), "APD").title(),
               "task": translate_status(row.get("task_type")),
               "status": translate_status(row.get("task_status"))}
              for _, row in sorted(by_version.items())[-20:]]
    if active:
        events = (events + [{"time": _time(runtime.get("updated_at")), "session": _text(selected, "APD").title(),
                             "task": translate_status(runtime.get("task_type")), "status": "工作中"}])[-20:]
    # A receipt from a previous turn must not be presented as this turn's usage.
    receipt = next((r for r in reversed(receipts) if r.get("turn_id") == runtime.get("turn_id") and runtime.get("turn_id")), {})
    if not runtime and receipts:
        receipt = receipts[-1]
    task_type = _text(runtime.get("task_type"))
    permission = _text(runtime.get("permission_mode"))
    changed = runtime.get("files_changed")
    if type(changed) is not int:
        changed_files = state.get("changed_files", [])
        changed = len(changed_files) if isinstance(changed_files, list) else 0
    task = _text(runtime.get("task"), "等待开发任务")
    return {
        "status": "正在运行" if active else translate_status(status),
        "failed": status == "FAILED", "active": active,
        "stage": translate_status(runtime.get("stage", "IDLE")),
        "waiting": "等待状态更新" if waiting else "本地只读观察 · 每 400 ms 更新",
        "repo": _text(runtime.get("repo")), "version": _text(runtime.get("state_version", state.get("state_version", 0))),
        "task": task, "taskType": f"{task_type} / {translate_status(task_type)}",
        "permission": f"{permission} / {translate_status(permission)}",
        "route": _text(selected).title(), "reason": _text(runtime.get("router_reason")),
        "model": _text(runtime.get("model")), "thread": short_id(runtime.get("thread_id")),
        "turn": short_id(runtime.get("turn_id")),
        "resume": "是" if runtime.get("session_resumed") is True else ("否" if runtime.get("session_resumed") is False else "—"),
        "head": _text(runtime.get("head", state.get("repository_head")))[:8],
        "worktree": f"{changed} 个文件有变更" if changed else "干净",
        "blocker": _text(state.get("current_blocker"), "无"),
        "nextAction": _text(state.get("next_action"), "等待下一任务"),
        "error": _text(runtime.get("error_message"), ""),
        "sessions": cards, "events": events, "usage": format_usage(receipt.get("usage")),
    }


def state_dir_for_repo(repo: Path) -> Path:
    # This is the GUI's only Git command. It reads the metadata location, including worktrees.
    cp = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo, text=True, capture_output=True)
    if cp.returncode:
        raise ValueError("目标目录不是可读取的 Git 仓库")
    return Path(cp.stdout.strip()) / "apd"


def qml_resource():
    return resources.as_file(resources.files("apd_ui").joinpath("Main.qml"))


def create_engine(state_dir: Path, qml_path: Path):
    # Helpers stay importable even when PySide6 is unavailable.
    from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal
    from PySide6.QtQml import QQmlApplicationEngine

    class Monitor(QObject):
        changed = Signal()

        def __init__(self):
            super().__init__()
            self.raw = {}
            self.view = observation_view({}, True)
            self.timer = QTimer(self)
            self.timer.setInterval(400)
            self.timer.timeout.connect(self.refresh)
            self.refresh()
            self.timer.start()

        @Property("QVariantMap", notify=changed)
        def data(self):
            return self.view

        def refresh(self):
            try:
                self.raw, waiting = read_observation(state_dir, self.raw)
                view = observation_view(self.raw, waiting)
            except Exception:
                view = dict(self.view, waiting="等待状态更新")
            if view != self.view:
                self.view = view
                self.changed.emit()

    monitor = Monitor()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("monitor", monitor)
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    return engine, monitor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apd-gui", description="APD 多模型开发监视器（只读）")
    parser.add_argument("--repo", default=".", help="目标 Git 仓库")
    parser.add_argument("--state-dir", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        from PySide6.QtGui import QGuiApplication
        state_dir = Path(args.state_dir) if args.state_dir else state_dir_for_repo(Path(args.repo).resolve())
        app = QGuiApplication([sys.argv[0]])
        app.setApplicationName("APD 多模型开发监视器")
        with qml_resource() as path:
            engine, monitor = create_engine(state_dir, path)
            if not engine.rootObjects():
                print("APD_GUI_WARNING: 无法加载监控界面。", file=sys.stderr)
                return 1
            return app.exec()
    except Exception:
        print("APD_GUI_WARNING: 无法启动监控窗口；Core 不受影响。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
