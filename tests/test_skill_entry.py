import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import apd


ROOT = Path(apd.__file__).resolve().parent


class SkillEntryTests(unittest.TestCase):
    def skill(self):
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        skills = (ROOT / plugin["skills"]).resolve()
        paths = list(skills.glob("*/SKILL.md"))
        self.assertEqual(paths, [skills / "apd" / "SKILL.md"])
        text = paths[0].read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match, "Missing YAML frontmatter")
        fields = dict(line.split(":", 1) for line in match.group(1).splitlines())
        return {key: value.strip() for key, value in fields.items()}, text[match.end():]

    def test_manifest_discovers_one_skill_named_apd(self):
        fields, _ = self.skill()
        self.assertEqual(fields["name"], "apd")
        self.assertTrue(fields["description"])
        self.assertFalse((ROOT / "skills" / "automated-development").exists())

    def test_description_matches_development_without_explicit_only_rule(self):
        fields, body = self.skill()
        description = fields["description"].lower()
        for intent in (r"fix|bug", r"implement|feature", r"refactor", r"investigat", r"validat", r"review"):
            with self.subTest(intent=intent):
                self.assertRegex(description, intent)
        self.assertIn("local git repository", description)
        self.assertIn("multi-step software development", description)
        for explicit_only in ("only when the user explicitly asks", "仅在用户明确要求使用 APD", "Use APD when the user asks to use APD"):
            self.assertNotIn(explicit_only.casefold(), (description + body).casefold())

    def test_skill_checks_worker_environment_before_invocation(self):
        _, body = self.skill()
        first_instruction = body.strip().splitlines()[0]
        self.assertIn("APD_INTERNAL_WORKER=1", first_instruction)
        for forbidden in ("APD Skill", "apd develop", "apd run", "GUI"):
            self.assertIn(forbidden, first_instruction)

    def test_skill_uses_modules_for_development_single_steps_and_status(self):
        _, body = self.skill()
        for command in ("python -m apd develop", "python -m apd run", "python -m apd status"):
            self.assertIn(command + ' --repo "<git-root>"', body)
        self.assertIn('python -m apd_gui --repo "<git-root>"', body)
        # Inspect invocation examples, allowing mentions of the command names.
        examples = re.findall(r"`([^`\n]+)`", body)
        examples += re.findall(r"```bash\n(.*?)\n```", body, re.DOTALL)
        for example in examples:
            for line in example.splitlines():
                self.assertNotRegex(line.strip(), r"^apd(?:-gui)?\s+\S+")
        self.assertIn("不要求 `apd` 或 `apd-gui` 位于 PATH", body)

    def test_no_mcp_configuration_or_plugin_dependency(self):
        for filename in ("mcp.json", ".mcp.json", ".app.json"):
            self.assertFalse(list(ROOT.rglob(filename)), filename)
        for filename in ("plugin.json", ".codex-plugin/plugin.json"):
            manifest = json.loads((ROOT / filename).read_text(encoding="utf-8"))
            self.assertNotIn("mcpServers", manifest)


class ModuleEntrypointTests(unittest.TestCase):
    def test_modules_work_without_console_scripts_on_path(self):
        base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        scripts = {Path(sysconfig.get_path("scripts")).resolve(),
                   Path(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user"))).resolve()}
        paths = [str(base_python.parent)]
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            path = Path(directory.strip('"')).resolve()
            if path in scripts or any((path / name).exists() for name in ("apd", "apd.exe", "apd-gui", "apd-gui.exe")):
                continue
            paths.append(str(path))
        env = dict(os.environ, PATH=os.pathsep.join(paths), PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        self.assertTrue(base_python.is_file())
        self.assertEqual(Path(shutil.which(base_python.name, path=env["PATH"])).resolve(), base_python)
        self.assertIsNone(shutil.which("apd", path=env["PATH"]))
        self.assertIsNone(shutil.which("apd-gui", path=env["PATH"]))
        with tempfile.TemporaryDirectory() as td:
            for module, flags, expected in (("apd", ["--version"], "apd 0.3.2"),
                                           ("apd", ["--help"], "usage: apd"),
                                           ("apd", ["develop", "--help"], "--no-gui"),
                                           ("apd", ["run", "--help"], "--type"),
                                           ("apd_gui", ["--help"], "usage: apd-gui")):
                with self.subTest(module=module, flags=flags):
                    # Windows may resolve the executable before applying env.
                    result = subprocess.run([str(base_python), "-m", module, *flags], cwd=td, env=env,
                                            capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(expected, result.stdout)


class WorkerGuardTests(unittest.TestCase):
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

    def test_run_and_develop_child_guard_parent_unchanged_on_success_and_failure(self):
        for command in ("run", "develop"):
            for original in (None, "0", "already-set"):
                for fail in (False, True):
                    with self.subTest(command=command, original=original, fail=fail), patch.dict(os.environ):
                        if original is None:
                            os.environ.pop("APD_INTERNAL_WORKER", None)
                        else:
                            os.environ["APD_INTERNAL_WORKER"] = original
                        before = dict(os.environ)
                        events = []

                        class FakeRuntime:
                            def __init__(self, config):
                                self.environment = dict(os.environ, **config.env)
                                events.append(("created", self.environment["APD_INTERNAL_WORKER"]))

                            def __enter__(self):
                                return self

                            def __exit__(self, *_):
                                events.append(("closed", self.environment["APD_INTERNAL_WORKER"]))

                            def thread_start(self, **kwargs):
                                return SimpleNamespace(id="worker-test-thread", run=self.run)

                            def thread_resume(self, *args, **kwargs):
                                events.append(("resumed", self.environment["APD_INTERNAL_WORKER"]))
                                return self.thread_start(**kwargs)

                            def run(self, prompt, **kwargs):
                                events.append(("turn", self.environment["APD_INTERNAL_WORKER"]))
                                if fail:
                                    raise RuntimeError("Worker failed")
                                return SimpleNamespace(id="worker-test-turn", usage=None,
                                    final_response=json.dumps({
                                        "status": "PASS", "summary": "Checked", "accepted_facts": [],
                                        "current_blocker": None, "next_action": "", "needs_deep_reasoning": False,
                                    }))

                        # Replace only the runtime constructor, exercising the real
                        # APD SDK factory and its official CodexConfig.env argument.
                        with patch("openai_codex.Codex", FakeRuntime), \
                             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            result = apd.main(["--models", str(ROOT / "models.toml"), command,
                                               "--repo", str(self.repo), "--task", "fix a bug", "--no-gui"])
                        self.assertEqual(result, 2 if fail else 0)
                        self.assertEqual(events[0], ("created", "1"))
                        self.assertEqual(events[-1], ("closed", "1"))
                        self.assertEqual(sum(event == "turn" for event, _ in events),
                                         1 if fail or command == "run" else 4)
                        self.assertTrue(all(value == "1" for _, value in events))
                        self.assertTrue(dict(os.environ) == before, "APD changed the parent environment")

    def test_official_sdk_passes_guard_to_child_before_launch_and_preserves_parent(self):
        coordinator = apd.Coordinator(self.repo, ROOT / "models.toml")
        for original in (None, "custom-parent-value"):
            with self.subTest(original=original), patch.dict(os.environ):
                if original is None:
                    os.environ.pop("APD_INTERNAL_WORKER", None)
                else:
                    os.environ["APD_INTERNAL_WORKER"] = original
                before = dict(os.environ)
                child_values = []

                def intercept_launch(*args, **kwargs):
                    child_values.append(kwargs["env"].get("APD_INTERNAL_WORKER"))
                    raise OSError("Test stops before launching any Codex process")

                runtime, _, _ = coordinator._sdk()
                with patch("openai_codex.client._resolve_codex_bin", return_value=Path("fake-codex")), \
                     patch("openai_codex.client._installed_codex_path_dirs", return_value=()), \
                     patch("openai_codex.client.subprocess.Popen", side_effect=intercept_launch):
                    with self.assertRaises(OSError):
                        runtime()
                self.assertEqual(child_values, ["1"])
                self.assertTrue(dict(os.environ) == before, "Runtime startup changed the parent environment")

    def test_every_worker_prompt_has_second_recursion_guard(self):
        coordinator = apd.Coordinator(self.repo, ROOT / "models.toml")
        guard = ("You are an APD internal worker.\n"
                 "Do not invoke the APD skill, APD CLI, or another APD development loop.\n"
                 "Execute only the assigned worker task directly.\n")
        for task_type in apd.TaskType:
            with self.subTest(task_type=task_type):
                route = coordinator.router.route(task_type)
                prompt = coordinator._prompt("Assigned task", route, "{}", "")
                self.assertTrue(prompt.startswith(guard))
                self.assertIn(f"Task type: {task_type.value}", prompt)
                self.assertIn(f"Permission: {route.permission.value}", prompt)


if __name__ == "__main__":
    unittest.main()
