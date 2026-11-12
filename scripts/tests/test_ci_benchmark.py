"""Verify benchmark comparison and exact-project teardown without Docker."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_benchmark", ROOT / "scripts/ci-benchmark-backend.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class Benchmark(unittest.TestCase):
    def row(self, workers=2, seconds=20, tests=1729, skipped=0, **changes):
        return {"workers": workers, "seconds": seconds, "exit_code": 0, "cleanup_code": 0,
                "report": {"tests": tests, "skipped": skipped, "failures": 0, "errors": 0}, **changes}

    def test_uses_median_and_refuses_failed_or_different_suites(self):
        rows = [self.row(2, 20), self.row(2, 22), self.row(3, 14), self.row(3, 16)]
        self.assertEqual(benchmark.recommendation(rows), 3)
        for bad in (self.row(exit_code=1), self.row(cleanup_code=1), self.row(tests=1700),
                    self.row(skipped=1), self.row(report_error="missing report")):
            with self.subTest(bad=bad):
                self.assertIsNone(benchmark.recommendation([rows[0], bad]))

    def test_reads_junit_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "junit.xml").write_text('<testsuites><testsuite tests="1729" failures="0" errors="0" skipped="0" /></testsuites>')
            self.assertEqual(benchmark.report_summary(directory), self.row()["report"])

    def test_run_scopes_commands_and_cleans_up_after_interrupt(self):
        compose = ["docker", "compose", "-p", "ifora-ci-benchmark-test", "-f", "test-compose.yml"]
        calls = []
        process = SimpleNamespace(stdout=iter(["suite output\n"]), wait=lambda: 0, poll=lambda: 0)
        def run(args, **kwargs):
            calls.append(args)
            if "cp" in args:
                (Path(args[-1]) / "junit.xml").write_text('<testsuites><testsuite tests="1729" failures="0" errors="0" skipped="0" /></testsuites>')
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(benchmark, "sample_resources"), \
             patch.object(benchmark.subprocess, "Popen", return_value=process) as popen, \
             patch.object(benchmark.subprocess, "run", side_effect=run):
            result = benchmark.run_once(compose, 3, Path(tmp) / "run")
            self.assertEqual(result["report"]["tests"], 1729)
            self.assertEqual(popen.call_args.kwargs["env"]["CI_TEST_WORKERS"], "3")
            self.assertEqual(popen.call_args.kwargs["env"]["CI_TEST_PROFILE"], "1")
            self.assertEqual(calls[-1], compose + ["down", "--volumes"])
            popen.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                benchmark.run_once(compose, 4, Path(tmp) / "interrupted")
            self.assertEqual(calls[-1], compose + ["down", "--volumes"])


if __name__ == "__main__":
    unittest.main()
