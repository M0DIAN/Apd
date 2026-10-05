import contextlib
import io
import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import apd
import apd_gui
from test_gui import FAKE_SDK, FakeCodex


ROOT = Path(apd.__file__).resolve().parent
USAGE = json.loads((Path(__file__).parent / "fixtures" / "sdk_usage.json").read_text(encoding="utf-8"))
MODELS = {"luna": "gpt-6-luna", "sol": "gpt-6.1-sol", "astra": "gpt-6-astra"}


def receipt(session, stage, version, duration, status="PASS", run_id="current", effort="high"):
    return {"run_id": run_id, "state_version": version, "router_selected_session": session,
            "task_type": stage, "task_status": status, "requested_model": MODELS[session],
            "requested_effort": effort, "duration_ms": duration, "turn_id": f"fixture-turn-{version}",
            "updated_at": "2026-01-01T00:00:00+00:00"}


def completed_run():
    rows = [receipt("luna", "DISCOVERY", 1, 12000), receipt("sol", "IMPLEMENTATION", 2, 30000),
            receipt("sol", "TEST", 3, 18000), receipt("astra", "REVIEW", 4, 17000)]
    rows[-1]["usage"] = USAGE
    return {"runtime": {"run_id": "current", "status": "COMPLETED", "stage": "COMPLETED",
                        "router_selected_session": "astra", "model": MODELS["astra"], "effort": "high",
                        "models": MODELS, "efforts": dict.fromkeys(MODELS, "high"),
                        "turn_id": "fixture-turn-4", "state_version": 4},
            "receipts": rows, "history": [dict(row) for row in rows]}


class UsageNormalizationTests(unittest.TestCase):
    def test_real_nested_total_shape(self):
        result = apd_gui.format_usage(USAGE)
        for name, expected in {"input": "69,702", "cached": "49,408", "output": "1,177",
                               "reasoning": "752", "total": "70,879", "source": "SDK Total",
                               "available": True}.items():
            self.assertEqual(result[name], expected, name)
        self.assertIn("不代表完整 Token 总量或最终账单", result["notice"])

    def test_nested_last_fallback(self):
        for usage in ({"last": USAGE["last"]}, {"total": None, "last": USAGE["last"]}):
            with self.subTest(usage=usage):
                result = apd_gui.format_usage(usage)
                self.assertEqual(result["source"], "SDK Last")
                self.assertEqual(result["input"], "18,115")
                self.assertEqual(result["total"], "18,492")
                self.assertEqual(result["reasoning"], "144")
                self.assertTrue(result["available"])

    def test_flat_camel_case(self):
        result = apd_gui.format_usage(USAGE["total"])
        self.assertEqual([result[key] for key in ("input", "cached", "output", "reasoning", "total")],
                         ["69,702", "49,408", "1,177", "752", "70,879"])
        self.assertEqual(result["source"], "Flat Usage")
        self.assertTrue(result["available"])

    def test_flat_snake_case(self):
        result = apd_gui.format_usage({"input_tokens": 1000, "cached_input_tokens": 0,
                                      "output_tokens": 5, "reasoning_tokens": 0, "total_tokens": 1005})
        self.assertEqual([result[key] for key in ("input", "cached", "output", "reasoning", "total")],
                         ["1,000", "0", "5", "0", "1,005"])
        self.assertTrue(result["available"])

    def test_total_is_not_computed_from_components(self):
        result = apd_gui.format_usage({"inputTokens": 10, "outputTokens": 2})
        self.assertTrue(result["available"])
        self.assertEqual(result["total"], "—")
        self.assertEqual(apd_gui.format_usage({"totalTokens": 0})["total"], "0")

    def test_selected_total_does_not_fall_through_to_last(self):
        result = apd_gui.format_usage({"total": {}, "last": USAGE["last"]})
        self.assertFalse(result["available"])
        self.assertEqual(result["source"], "SDK Total")
        self.assertEqual(result["message"], "当前运行时未提供可解析的用量信息")

    def test_unparseable_counts_are_unknown(self):
        for usage in (None, [], {"inputTokens": True, "outputTokens": -1, "totalTokens": "42"},
                      {"last": {"inputTokens": 1.5}}):
            with self.subTest(usage=usage):
                result = apd_gui.format_usage(usage)
                self.assertFalse(result["available"])
                self.assertEqual(result["total"], "—")


class ObservationTests(unittest.TestCase):
    def view(self, raw):
        return apd_gui.observation_view(raw, False)

    def test_completed_cards_keep_pass_and_actual_model_effort(self):
        raw = completed_run()
        raw["runtime"]["efforts"]["astra"] = "low"
        cards = self.view(raw)["sessions"]
        self.assertEqual([card["model"] for card in cards], list(MODELS.values()))
        self.assertEqual([card["effort"] for card in cards], ["high / 高"] * 3)
        self.assertEqual([card["result"] for card in cards], ["PASS"] * 3)
        self.assertEqual([card["status"] for card in cards],
                         ["✓ 通过 · 12s", "✓ 通过 · 48s", "✓ 通过 · 17s"])
        self.assertTrue(all(not card["active"] for card in cards))
        self.assertEqual(cards[-1]["role"], "独立复核")

    def test_current_run_filters_cards_events_and_usage(self):
        raw = completed_run()
        old = receipt("astra", "GENERAL", 99, 999000, "FAIL", "old")
        old["usage"] = {"inputTokens": 999999}
        old["turn_id"] = "fixture-turn-4"
        raw["receipts"].append(old)
        raw["history"].append(old)
        result = self.view(raw)
        self.assertEqual(result["sessions"][-1]["status"], "✓ 通过 · 17s")
        self.assertEqual([row["task"] for row in result["events"]], ["发现", "实施", "验证", "独立复核"])
        self.assertEqual(result["usage"]["total"], "70,879")
        self.assertEqual(result["usage"]["source"], "SDK Total")

    def test_new_run_does_not_borrow_tagged_history(self):
        raw = completed_run()
        raw["runtime"]["run_id"] = "new"
        result = self.view(raw)
        self.assertEqual([card["status"] for card in result["sessions"]], ["待命"] * 3)
        self.assertEqual(result["events"], [])
        self.assertFalse(result["usage"]["available"])

    def test_legacy_receipts_use_latest_without_guessing_effort(self):
        raw = completed_run()
        raw["runtime"].pop("run_id")
        for row in raw["receipts"] + raw["history"]:
            row.pop("run_id", None)
            row.pop("requested_effort", None)
            row.pop("duration_ms", None)
        result = self.view(raw)
        self.assertEqual(result["sessions"][1]["status"], "✓ 通过")
        self.assertEqual(result["sessions"][1]["effort"], "—")
        self.assertEqual(result["usage"]["total"], "70,879")

    def test_legacy_logs_still_work_when_runtime_has_run_id(self):
        raw = completed_run()
        for row in raw["receipts"] + raw["history"]:
            row.pop("run_id", None)
        cards = self.view(raw)["sessions"]
        self.assertEqual(cards[1]["status"], "✓ 通过 · 18s")
        self.assertEqual(cards[-1]["status"], "✓ 通过 · 17s")

    def test_mixed_logs_do_not_leak_legacy_events_into_tagged_run(self):
        raw = completed_run()
        old = receipt("luna", "GENERAL", 99, 1000, "FAIL")
        old.pop("run_id")
        raw["history"] = [old]
        self.assertNotIn("常规任务", [row["task"] for row in self.view(raw)["events"]])

    def test_active_card_overrides_prior_pass_with_current_request(self):
        raw = completed_run()
        raw["runtime"].update(status="MODEL_RUNNING", router_selected_session="sol",
                              model="fixture-current-model", effort="medium")
        card = self.view(raw)["sessions"][1]
        self.assertTrue(card["active"])
        self.assertEqual(card["status"], "● 工作中")
        self.assertEqual(card["model"], "fixture-current-model")
        self.assertEqual(card["effort"], "medium / 中")

    def test_sol_merges_implementation_and_test(self):
        card = self.view(completed_run())["sessions"][1]
        self.assertEqual(card["role"], "实施 / 验证")
        self.assertEqual(card["status"], "✓ 通过 · 48s")

    def test_sol_any_failure_or_blocker_is_visible(self):
        for status, expected in (("FAIL", "✕ 失败"), ("BLOCKED", "! 阻塞")):
            with self.subTest(status=status):
                raw = completed_run()
                raw["receipts"][1]["task_status"] = status
                self.assertEqual(self.view(raw)["sessions"][1]["status"], expected + " · 48s")

    def test_astra_merges_deep_reasoning_and_review(self):
        raw = completed_run()
        raw["receipts"].insert(1, receipt("astra", "DEEP_REASONING", 0, 5000))
        card = self.view(raw)["sessions"][-1]
        self.assertEqual(card["role"], "深度分析 / 独立复核")
        self.assertEqual(card["status"], "✓ 通过 · 22s")

    def test_duration_has_subsecond_precision_and_requires_complete_evidence(self):
        raw = completed_run()
        raw["receipts"][0]["duration_ms"] = 12341
        raw["receipts"][1].pop("duration_ms")
        cards = self.view(raw)["sessions"]
        self.assertEqual(cards[0]["status"], "✓ 通过 · 12.3s")
        self.assertEqual(cards[1]["status"], "✓ 通过")

    def test_uncalled_models_remain_idle(self):
        raw = completed_run()
        raw["receipts"] = raw["receipts"][:1]
        raw["history"] = []
        self.assertEqual([card["status"] for card in self.view(raw)["sessions"]],
                         ["✓ 通过 · 12s", "待命", "待命"])

    def test_failed_step_without_receipt_does_not_look_uncalled(self):
        raw = completed_run()
        raw["receipts"] = raw["receipts"][:3]
        raw["runtime"].update(status="FAILED", turn_id=None)
        self.assertEqual(self.view(raw)["sessions"][-1]["status"], "✕ 失败")

    def test_failed_request_uses_runtime_model_effort_instead_of_prior_receipt(self):
        raw = completed_run()
        raw["runtime"].update(status="FAILED", router_selected_session="sol", turn_id=None,
                              model="fixture-failed-model", effort="xhigh")
        card = self.view(raw)["sessions"][1]
        self.assertEqual(card["status"], "✕ 失败")
        self.assertEqual(card["model"], "fixture-failed-model")
        self.assertEqual(card["effort"], "xhigh")

    def test_known_and_unknown_effort_mapping(self):
        for value, expected in (("low", "low / 低"), ("medium", "medium / 中"),
                                ("high", "high / 高"), ("xhigh", "xhigh"), (None, "—")):
            with self.subTest(value=value):
                self.assertEqual(apd_gui.format_effort(value), expected)
        raw = completed_run()
        raw["receipts"][-1]["requested_effort"] = "xhigh"
        raw["runtime"]["effort"] = "xhigh"
        result = self.view(raw)
        self.assertEqual(result["effort"], "xhigh")
        self.assertEqual(result["sessions"][-1]["effort"], "xhigh")

    def test_polling_caption_is_one_second(self):
        self.assertEqual(self.view(completed_run())["waiting"], "本地只读观察 · 每 1 秒更新")


class ExecutionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (("init",), ("config", "user.email", "apd@example.invalid"),
                     ("config", "user.name", "APD Test")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        for args in (("add", "."), ("commit", "-m", "test base")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.sdk = patch.object(apd.Coordinator, "_sdk", return_value=FAKE_SDK)
        self.sdk.start()
        self.addCleanup(self.sdk.stop)
        self.coordinator = apd.Coordinator(self.repo, ROOT / "models.toml")

    def step(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.coordinator.run_step(FakeCodex(), "fixture task", apd.TaskType.IMPLEMENTATION)

    def test_effort_records_exact_argument_not_later_config(self):
        original = FakeCodex.run
        requested = []

        def run(worker, *args, **kwargs):
            requested.append(kwargs["effort"])
            self.coordinator.models["sol"]["effort"] = "low"
            return original(worker, *args, **kwargs)

        with patch.object(FakeCodex, "run", run):
            result = self.step()
        recorded = apd_gui.tail_jsonl_safe(self.coordinator.store.receipts_path)[-1]
        runtime = apd_gui.load_json_safe(self.coordinator.store.runtime_path)
        self.assertEqual(requested, ["high"])
        self.assertEqual(result["receipt"]["requested_effort"], "high")
        self.assertEqual(recorded["requested_effort"], "high")
        self.assertEqual(runtime["effort"], "high")
        self.assertEqual(runtime["efforts"], dict.fromkeys(MODELS, "high"))

    def test_run_id_is_observer_metadata_not_canonical_state(self):
        result = self.step()
        runtime = apd_gui.load_json_safe(self.coordinator.store.runtime_path)
        history = apd_gui.tail_jsonl_safe(self.coordinator.store.history_path)[-1]
        receipt_row = apd_gui.tail_jsonl_safe(self.coordinator.store.receipts_path)[-1]
        self.assertRegex(runtime["run_id"], re.compile(r"^[0-9a-f]{32}$"))
        self.assertEqual(history["run_id"], runtime["run_id"])
        self.assertEqual(receipt_row["run_id"], runtime["run_id"])
        for key in ("run_id", "started_at", "duration_ms", "requested_effort"):
            self.assertNotIn(key, result["state"])

    def test_step_duration_uses_monotonic_and_has_utc_start(self):
        clock = Mock(side_effect=[50.0, 62.341])
        with patch.object(apd, "time", SimpleNamespace(monotonic=clock)):
            result = self.step()
        row = result["receipt"]
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(row["duration_ms"], 12341)
        self.assertEqual(datetime.fromisoformat(row["started_at"]).utcoffset(), timezone.utc.utcoffset(None))
        history = apd_gui.tail_jsonl_safe(self.coordinator.store.history_path)[-1]
        runtime = apd_gui.load_json_safe(self.coordinator.store.runtime_path)
        self.assertEqual(history["duration_ms"], 12341)
        self.assertEqual(history["started_at"], row["started_at"])
        self.assertEqual(runtime["duration_ms"], 12341)

    def test_each_cli_run_and_develop_gets_a_new_shared_run_id(self):
        ids = []
        for command in ("run", "develop"):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(apd.main(["--models", str(ROOT / "models.toml"), command,
                                           "--repo", str(self.repo), "--task", "fixture task", "--no-gui"]), 0)
            runtime = apd_gui.load_json_safe(self.coordinator.store.runtime_path)
            ids.append(runtime["run_id"])
            rows = apd_gui.tail_jsonl_safe(self.coordinator.store.receipts_path)
            current_rows = rows[-(1 if command == "run" else 4):]
            self.assertTrue(all(row["run_id"] == runtime["run_id"] for row in current_rows))
            self.assertEqual(runtime["status"], "COMPLETED")
        self.assertNotEqual(*ids)
        history = apd_gui.tail_jsonl_safe(self.coordinator.store.history_path)
        self.assertEqual([row["run_id"] for row in history], [ids[0]] + [ids[1]] * 4)

    def test_non_pass_worker_still_records_observation_metadata(self):
        response = dict(FakeCodex.response, status="BLOCKED", current_blocker="fixture blocker")
        with patch.object(FakeCodex, "response", response):
            result = self.step()
        row = result["receipt"]
        self.assertEqual(row["task_status"], "BLOCKED")
        self.assertEqual(row["requested_effort"], "high")
        self.assertEqual(row["run_id"], self.coordinator.run_id)
        self.assertIsInstance(row["duration_ms"], int)


if __name__ == "__main__":
    unittest.main()
