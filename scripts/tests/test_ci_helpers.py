"""CI helper tests run without application secrets, Docker or Slack delivery."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


slack = module("ci_slack", "scripts/ci-slack.py")
resources = module("ci_resources", "backend/tests/ci_resources.py")
backend = module("ci_backend", "scripts/ci-test-backend.py")


class WorkerIsolation(unittest.TestCase):
    def env(self):
        return {"TEST_DB_NAME": "ifora_ci_test", "TEST_REDIS_DB": "15",
                "DATABASE_URL": "postgresql+psycopg2://ifora_ci:ci_only@ci-postgres:5432/postgres",
                "REDIS_URL": "redis://ci-redis:6379/0"}

    def test_workers_have_disjoint_resources(self):
        pairs = [resources.worker_resources({**self.env(), "PYTEST_XDIST_WORKER": f"gw{i}"}) for i in range(4)]
        self.assertEqual(len({p[0] for p in pairs}), 4)
        self.assertEqual([p[1] for p in pairs], ["11", "12", "13", "14"])
        self.assertEqual(resources.worker_resources(self.env()), ("ifora_ci_test", "15"))

    def test_refuses_non_ci_or_unexpected_worker(self):
        for patch in [{"PYTEST_XDIST_WORKER": "gw4"}, {"PYTEST_XDIST_WORKER": "gw0;DROP"},
                      {"TEST_DB_NAME": "ifora"}, {"REDIS_URL": "redis://ifora-redis:6379/0"},
                      {"TEST_REDIS_DB": "0"}, {"DATABASE_URL": "postgresql://ifora@localhost/ifora"}]:
            with self.subTest(patch=patch), self.assertRaises(RuntimeError):
                resources.worker_resources({**self.env(), "PYTEST_XDIST_WORKER": "gw0", **patch})

    def test_entrypoint_refuses_deployed_database(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {**self.env(), "DATABASE_URL": "postgresql+psycopg2://ifora:x@ifora-postgres:5432/ifora"}):
            with self.assertRaises(SystemExit):
                backend.validate_endpoints()

    def test_worker_arguments_keep_full_suite(self):
        from unittest.mock import patch
        for workers in ("1", "2", "4"):
            with patch.dict(os.environ, {**self.env(), "CI_TEST_WORKERS": workers}), \
                 patch.object(backend, "wait_for_services"), patch.object(backend.subprocess, "call", return_value=0) as call:
                self.assertEqual(backend.main(), 0)
                args = call.call_args.args[0]
                self.assertIn("--durations=25", args)
                self.assertNotIn("-k", args)
                self.assertNotIn("--ignore", args)
                if workers == "1":
                    self.assertNotIn("-n", args)
                else:
                    self.assertEqual(args[args.index("-n") + 1], workers)
                    self.assertIn("--dist=loadfile", args)


class SlackThread(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def env(self):
        return {"SLACK_BOT_TOKEN": "test-only", "SLACK_CHANNEL_ID": "C_TEST",
                "DRONE_REPO": "chanderinguva/ifora", "DRONE_BUILD_NUMBER": "9",
                "DRONE_COMMIT_BRANCH": "feature/<@everyone>", "DRONE_COMMIT_SHA": "0123456789abcdef",
                "DRONE_BUILD_LINK": "https://drone.ifora.app/chanderinguva/ifora/9",
                "DRONE_BUILD_STARTED": "123"}

    def test_one_parent_threaded_events_and_final_update(self):
        calls = []
        def api(method, payload, token):
            calls.append((method, payload))
            return {"ok": True, "ts": "123.456"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "results").mkdir()
            (root / "results/deploy-demo.json").write_text(json.dumps({"status": "success", "seconds": 25}))
            for event in ("start", "tests", "images", "demo", "success", "success"):
                slack.notify(event, self.env(), root, api)
            parents = [p for m, p in calls if m == "chat.postMessage" and "thread_ts" not in p]
            replies = [p for m, p in calls if "thread_ts" in p]
            self.assertEqual(len(parents), 1)
            self.assertEqual(len(replies), 4)
            self.assertTrue(all(p["thread_ts"] == "123.456" for p in replies))
            self.assertEqual(sum(m == "chat.update" for m, p in calls), 4)
            state = next((root / "slack").glob("*.json")).read_text()
            self.assertNotIn("test-only", state)
            self.assertIn("&lt;@everyone&gt;", json.dumps(parents[0]))

    def test_failed_parent_update_preserves_thread(self):
        calls = []
        def api(method, payload, token):
            calls.append((method, payload))
            if method == "chat.update":
                raise RuntimeError("simulated transport error")
            return {"ok": True, "ts": "123.456"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slack.notify("start", self.env(), root, api)
            with self.assertRaises(RuntimeError):
                slack.notify("images", self.env(), root, api)
            state = json.loads(next((root / "slack").glob("*.json")).read_text())
            self.assertEqual(state["ts"], "123.456")
            self.assertNotIn("images", state["events"])

    def test_failure_card_reports_partial_deployment(self):
        card = json.dumps(slack.blocks("failure", self.env(), {"deploy-demo": {"status": "success", "seconds": 25}, "deploy-local": {"status": "failure", "seconds": 30}}))
        self.assertIn("No automatic rollback", card)
        self.assertIn("0m 25s", card)
        self.assertIn("Not run / unreported", card)

    def test_missing_token_makes_no_request(self):
        def api(*args):
            self.fail("API called without a token")
        with self.assertRaises(RuntimeError):
            slack.notify("start", {"SLACK_CHANNEL_ID": "C_TEST"}, api=api)


class RecordCommand(unittest.TestCase):
    def test_records_and_preserves_failure_status(self):
        for status in (0, 17):
            with tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(["sh", str(ROOT / "scripts/ci-record.sh"), "test-backend", "sh", "-c", f"exit {status}"], cwd=tmp)
                self.assertEqual(result.returncode, status)
                data = json.loads((Path(tmp) / ".ci/results/test-backend.json").read_text())
                self.assertEqual(data["status"], "success" if status == 0 else "failure")
                self.assertGreaterEqual(data["seconds"], 0)


class DeploymentOptIn(unittest.TestCase):
    def test_access_is_opt_in_and_config_survives_cleanup(self):
        source = (ROOT / "scripts/ci-deploy.sh").read_text().split('case "${1:-}" in\n  build)', 1)[0]
        stubs = r'''
HOME_DIR="$CI_TEST_HOME"
LOCAL_ENV="$CI_TEST_HOME/env"
LOCAL_OVERRIDE="$CI_TEST_HOME/no-override"
LOCAL_SHA_FILE="$CI_TEST_HOME/sha"
ensure_image() { :; }
export_tree() { mkdir -p "$1/docker"; printf %s "$1" > "$CI_TEST_HOME/exported"; }
wait_healthy() { :; }
wait_http() { :; }
docker() { printf '%s\n' "$*" >> "$CI_TEST_HOME/calls"; return "${CI_TEST_DOCKER_STATUS:-0}"; }
deploy_local aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
'''
        for enabled, status in ((False, 0), (True, 0), (False, 17)):
            with tempfile.TemporaryDirectory(prefix="ifora helper ") as tmp:
                home = Path(tmp)
                (home / "env").write_text("IFORA_DEV_ACCESS_ENABLED=true\n" if enabled else "")
                harness = home / "harness.sh"
                harness.write_text(source + stubs)
                env = {**os.environ, "IMAGE_OWNER": "test", "CI_TEST_HOME": tmp, "CI_TEST_DOCKER_STATUS": str(status)}
                result = subprocess.run(["bash", str(harness)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                calls = (home / "calls").read_text()
                self.assertEqual("docker-compose.dev-access.yml" in calls, enabled)
                self.assertEqual("dev-edge dev-tunnel" in calls, enabled)
                exported = Path((home / "exported").read_text())
                self.assertEqual(exported.exists(), enabled)


if __name__ == "__main__":
    unittest.main()
