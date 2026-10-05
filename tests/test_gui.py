import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import apd
import apd_gui


ROOT = Path(apd.__file__).resolve().parent


class HelpersTests(unittest.TestCase):
    def test_json_missing_and_corrupt_preserve_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            fallback = {"status": "MODEL_RUNNING"}
            self.assertIs(apd_gui.load_json_safe(path, fallback), fallback)
            path.write_text('{"status":', encoding="utf-8")
            self.assertIs(apd_gui.load_json_safe(path, fallback), fallback)
            path.write_text('[]', encoding="utf-8")
            self.assertIs(apd_gui.load_json_safe(path, fallback), fallback)

    def test_json_valid(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            apd.atomic_json(path, {"status": "COMPLETED"})
            self.assertEqual(apd_gui.load_json_safe(path), {"status": "COMPLETED"})

    def test_tail_skips_partial_and_nonobject_lines(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.jsonl"
            path.write_text('{"state_version":1}\n[]\nbroken\n{"state_version":2}\n{"unfinished":', encoding="utf-8")
            self.assertEqual(apd_gui.tail_jsonl_safe(path, 1), [{"state_version": 2}])
            self.assertEqual(apd_gui.tail_jsonl_safe(path, 0), [])
            self.assertEqual(apd_gui.tail_jsonl_safe(path.with_name("missing")), [])

    def test_short_id(self):
        self.assertEqual(apd_gui.short_id("01a12345678947b1"), "01a1...47b1")
        self.assertEqual(apd_gui.short_id("short"), "short")
        self.assertEqual(apd_gui.short_id(None), "—")

    def test_chinese_mappings_preserve_unknown_protocol(self):
        for raw, label in (("IMPLEMENTATION", "实施"), ("REVIEW", "独立复核"),
                           ("READ_ONLY", "只读"), ("WORKSPACE_WRITE", "工作区写入"),
                           ("PASS", "通过"), ("BLOCKED", "阻塞"), ("COMPLETED", "已完成")):
            self.assertEqual(apd_gui.translate_status(raw), label)
        self.assertEqual(apd_gui.translate_status("FUTURE_STATUS"), "FUTURE_STATUS")

    def test_usage_only_displays_observed_counts(self):
        observed = apd_gui.format_usage({"input_tokens": 0, "output_tokens": 50,
                                         "input_tokens_details": {"cached_tokens": 12},
                                         "output_tokens_details": {"reasoning_tokens": 3}})
        self.assertEqual([observed[k] for k in ("input", "cached", "output", "reasoning")], ["0", "12", "50", "3"])
        self.assertEqual(observed["notice"], apd_gui.USAGE_NOTICE)
        unknown = apd_gui.format_usage({"total_tokens": 1000, "input_tokens": True})
        self.assertFalse(unknown["available"])
        self.assertEqual(unknown["message"], apd_gui.USAGE_UNAVAILABLE)

    def test_task_summary_identifies_task_and_hides_sensitive_content(self):
        self.assertEqual(apd.task_summary("修复导出按钮在空结果时的显示"), "修复导出按钮在空结果时的显示")
        for objective in ("fix token=PRIVATE_VALUE", "review auth.json", "change password PRIVATE_VALUE",
                          "def example():\n    return PRIVATE_VALUE",
                          "修复 https://alice:demo-value@example.invalid 的连接",
                          r"fix \\server\private", "fix /etc/private", r"fix C:\Users\example"):
            self.assertEqual(apd.task_summary(objective), "敏感配置或代码相关任务（正文已隐藏）")
        summary = apd.task_summary("修复导出按钮\nPRIVATE_BODY")
        self.assertEqual(summary, "修复导出按钮…")
        self.assertLessEqual(len(apd.task_summary("x" * 500)), 161)

    def test_missing_runtime_produces_waiting_view(self):
        with tempfile.TemporaryDirectory() as td:
            raw, waiting = apd_gui.read_observation(Path(td), {})
            view = apd_gui.observation_view(raw, waiting)
            self.assertEqual(view["waiting"], "等待状态更新")
            self.assertEqual(len(view["sessions"]), 3)
            self.assertEqual(view["usage"]["message"], apd_gui.USAGE_UNAVAILABLE)

    def test_failed_read_preserves_previous_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = {"runtime": {"status": "MODEL_RUNNING", "task": "当前任务"}}
            (root / "runtime.json").write_text("invalid", encoding="utf-8")
            raw, waiting = apd_gui.read_observation(root, previous)
            self.assertEqual(raw["runtime"], previous["runtime"])
            self.assertTrue(waiting)

    def test_usage_not_reused_for_a_different_turn(self):
        raw = {"runtime": {"turn_id": "new-turn"}, "receipts": [
            {"turn_id": "old-turn", "usage": {"input_tokens": 900}}]}
        self.assertFalse(apd_gui.observation_view(raw, False)["usage"]["available"])
        raw["runtime"]["turn_id"] = "old-turn"
        self.assertEqual(apd_gui.observation_view(raw, False)["usage"]["input"], "900")

    def test_gui_git_command_is_metadata_read_only(self):
        tree = ast.parse(Path(apd_gui.__file__).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "subprocess"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].func.attr, "run")
        self.assertEqual(ast.literal_eval(calls[0].args[0]), ["git", "rev-parse", "--absolute-git-dir"])
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertNotIn("apd", imports)
        self.assertNotIn("openai_codex", imports)


class FakeCodex:
    response = {
        "status": "PASS", "summary": "MODEL_RESPONSE_SENTINEL", "accepted_facts": [],
        "current_blocker": None, "next_action": "MODEL_NEXT_ACTION_SENTINEL", "needs_deep_reasoning": False,
    }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def thread_start(self, **kwargs):
        return SimpleNamespace(id="test-thread-0123456789", run=self.run)

    def thread_resume(self, *args, **kwargs):
        return self.thread_start(**kwargs)

    def run(self, *args, **kwargs):
        return SimpleNamespace(id="test-turn-0123456789", final_response=json.dumps(self.response),
                               usage={"input_tokens": 10, "output_tokens": 2})


FAKE_SDK = (FakeCodex, SimpleNamespace(read_only="read-only", workspace_write="workspace-write"),
            SimpleNamespace(deny_all="deny-all"))


class CoreObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (("init",), ("config", "user.email", "apd@example.invalid"),
                     ("config", "user.name", "APD Test")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "test base"], cwd=self.repo, check=True, capture_output=True)
        self.sdk = patch.object(apd.Coordinator, "_sdk", return_value=FAKE_SDK)
        self.sdk.start()
        self.addCleanup(self.sdk.stop)
        self.environment = patch.dict(os.environ, {"APD_GUI": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def command(self, name="run", *flags):
        args = ["--models", str(ROOT / "models.toml"), name, "--repo", str(self.repo)]
        if name != "status":
            args += ["--task", "fix token=OBJECTIVE_PRIVATE_SENTINEL", *flags]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return apd.main(args)

    def runtime(self):
        return apd_gui.load_json_safe(apd.StateStore(self.repo).runtime_path)

    def test_runtime_atomic_write_read(self):
        store = apd.StateStore(self.repo)
        store.save_runtime({"schema_version": 1, "status": "STARTING"})
        self.assertEqual(apd_gui.load_json_safe(store.runtime_path)["status"], "STARTING")
        self.assertFalse(store.runtime_path.with_suffix(".json.tmp").exists())
        self.assertFalse((self.repo / "runtime.json").exists())

    def test_no_gui_does_not_request_launch(self):
        with patch.object(apd, "launch_gui_best_effort") as launch:
            self.assertEqual(self.command("run", "--no-gui"), 0)
            self.assertEqual(self.command("develop", "--no-gui"), 0)
            launch.assert_not_called()

    def test_environment_disables_gui(self):
        with patch.dict(os.environ, {"APD_GUI": "0"}), patch.object(apd, "launch_gui_best_effort") as launch:
            self.assertEqual(self.command(), 0)
            launch.assert_not_called()

    def test_run_and_develop_request_gui_by_default(self):
        with patch.object(apd, "launch_gui_best_effort") as launch:
            self.assertEqual(self.command("run"), 0)
            self.assertEqual(self.command("develop"), 0)
            self.assertEqual(launch.call_count, 2)

    def test_status_never_starts_gui_or_publishes_runtime(self):
        with patch.object(apd, "launch_gui_best_effort") as launch:
            self.assertEqual(self.command("status"), 0)
            launch.assert_not_called()
        self.assertIsNone(self.runtime())

    def test_gui_launch_failure_core_completes_original_flow(self):
        original_popen = subprocess.Popen

        def fail_gui(args, **kwargs):
            if any(str(arg).endswith("apd_gui.py") for arg in args):
                raise OSError("GUI_LAUNCH_PRIVATE_SENTINEL")
            return original_popen(args, **kwargs)

        with patch.object(apd.subprocess, "Popen", side_effect=fail_gui):
            self.assertEqual(self.command(), 0)
        self.assertEqual(self.runtime()["status"], "COMPLETED")
        self.assertEqual(apd.StateStore(self.repo).load()["state_version"], 1)
        self.assertNotIn("GUI_LAUNCH_PRIVATE_SENTINEL", json.dumps(self.runtime()))

    def test_gui_launch_does_not_wait_or_share_streams(self):
        child = Mock()
        with patch.object(apd.subprocess, "Popen", return_value=child) as spawn:
            apd.launch_gui_best_effort(self.repo, self.repo / ".git" / "apd")
        child.wait.assert_not_called()
        child.communicate.assert_not_called()
        self.assertEqual(spawn.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(spawn.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_runtime_write_failure_is_nonblocking(self):
        with patch.object(apd.StateStore, "save_runtime", side_effect=PermissionError("denied")):
            self.assertEqual(self.command("develop", "--no-gui"), 0)
        self.assertEqual(apd.StateStore(self.repo).load()["state_version"], 4)

    def test_runtime_stages_and_private_content_exclusion(self):
        publications = []
        original_save = apd.StateStore.save_runtime

        def record(store, value):
            publications.append(dict(value))
            original_save(store, value)

        with patch.object(apd.StateStore, "save_runtime", record):
            self.assertEqual(self.command("develop", "--no-gui"), 0)
        stages = {p["stage"] for p in publications}
        self.assertTrue({"STARTING", "ROUTING", "SYNCING", "MODEL_RUNNING", "MERGING",
                         "VALIDATING", "REVIEWING", "COMPLETED"}.issubset(stages))
        serialized = json.dumps(publications)
        for private in ("OBJECTIVE_PRIVATE_SENTINEL", "MODEL_RESPONSE_SENTINEL", "MODEL_NEXT_ACTION_SENTINEL", "prompt", "final_response"):
            self.assertNotIn(private, serialized)
        self.assertEqual(self.runtime()["state_version"], 4)

    def test_failure_runtime_uses_stable_safe_description(self):
        with patch.object(FakeCodex, "run", side_effect=RuntimeError("AUTH_PRIVATE_SENTINEL")):
            self.assertEqual(self.command("run", "--no-gui"), 2)
        runtime = self.runtime()
        self.assertEqual((runtime["status"], runtime["stage"], runtime["error_code"]), ("FAILED", "FAILED", "APD_ERROR"))
        self.assertNotIn("AUTH_PRIVATE_SENTINEL", json.dumps(runtime))

    def test_observer_reads_do_not_change_target_repo(self):
        before = apd.snapshot(self.repo)
        root = apd_gui.state_dir_for_repo(self.repo)
        raw, waiting = apd_gui.read_observation(root, {})
        apd_gui.observation_view(raw, waiting)
        self.assertEqual(apd.snapshot(self.repo), before)
        self.assertFalse(root.exists())


class QmlTests(unittest.TestCase):
    def test_real_qml_loads_and_closes_offscreen(self):
        with tempfile.TemporaryDirectory() as td:
            code = '''
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
import apd_gui
app = QGuiApplication([])
with apd_gui.qml_resource() as path:
    assert path.is_file(), path
    engine, monitor = apd_gui.create_engine(Path.cwd(), path)
    assert engine.rootObjects(), "QML has no root objects"
    root = engine.rootObjects()[0]
    assert root.title() == "APD 多模型开发监视器"
    assert monitor.timer.interval() == 400
    assert len(monitor.data["sessions"]) == 3
    QTimer.singleShot(100, root.close)
    assert app.exec() == 0
'''
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QSG_RHI_BACKEND="software")
            cp = subprocess.run([sys.executable, "-c", code], cwd=td, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
            self.assertNotIn("ReferenceError", cp.stderr)
            self.assertNotIn("TypeError", cp.stderr)


if __name__ == "__main__":
    unittest.main()
