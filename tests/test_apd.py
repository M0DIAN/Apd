import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import apd


class RoutingTests(unittest.TestCase):
    def test_discovery(self):
        self.assertEqual(apd.TaskClassifier().classify("locate the call chain"), apd.TaskType.DISCOVERY)

    def test_implementation_routes_write_sol(self):
        route = apd.ModelRouter().route(apd.TaskType.IMPLEMENTATION)
        self.assertEqual((route.session, route.permission, route.channel), ("sol", apd.Permission.WORKSPACE_WRITE, "sol:write"))

    def test_review_routes_readonly_astra(self):
        route = apd.ModelRouter().route(apd.TaskType.REVIEW)
        self.assertEqual((route.session, route.permission, route.channel), ("astra", apd.Permission.READ_ONLY, "astra:review"))


class ResultTests(unittest.TestCase):
    def test_parse_structured_result(self):
        out = apd.parse_result(json.dumps({
            "status": "PASS",
            "summary": "ok",
            "accepted_facts": [],
            "current_blocker": None,
            "next_action": "",
            "needs_deep_reasoning": False,
        }))
        self.assertEqual(out["status"], "PASS")

    def test_missing_field_fails(self):
        with self.assertRaises(apd.APDError):
            apd.parse_result('{"status":"PASS"}')


class StateTests(unittest.TestCase):
    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "apd@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "APD Test"], cwd=repo, check=True)
            (repo / "x.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
            store = apd.StateStore(repo)
            state = store.load()
            self.assertEqual(state["state_version"], 0)
            state["state_version"] = 1
            store.save(state)
            self.assertEqual(store.load()["state_version"], 1)


if __name__ == "__main__":
    unittest.main()
