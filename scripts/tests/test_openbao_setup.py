"""Operator helper tests: no paid service, Docker daemon or real credentials."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("openbao_setup", ROOT / "scripts/openbao-setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class OpenBaoOperator(unittest.TestCase):
    def test_preparation_refuses_repository_storage(self):
        with self.assertRaises(RuntimeError):
            setup.prepare(ROOT / "unsafe-secrets", "dev")

    def test_operator_only_accepts_loopback_https(self):
        for url in ("http://localhost:18200", "https://evil.example", "https://root:token@localhost:18200"):
            with self.subTest(url=url), patch("sys.argv", ["setup", "status", "--directory", "/tmp/unused", "--url", url]):
                with self.assertRaises(RuntimeError):
                    setup.main()

    def test_configuration_uses_distinct_app_roles_and_never_writes_root_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for service in ("api", "worker"):
                for suffix in ("role-id", "secret-id"):
                    (directory / (service + "-" + suffix)).write_text("")
            calls = []
            def request(url, ca, path, body=None, token=None, method="POST"):
                calls.append((path, body, token, method))
                if path.endswith("/role-id"):
                    return {"data": {"role_id": "ROLE_" + path.split("/")[3]}}
                if path.endswith("/secret-id"):
                    return {"data": {"secret_id": "SECRET_" + path.split("/")[3]}}
                return {"data": {}}
            with patch.object(setup, "request", request), contextlib.redirect_stdout(io.StringIO()) as output:
                setup.configure("https://localhost:18200", directory, "ROOT_SENTINEL")
            assert "ROOT_SENTINEL" not in output.getvalue()
            for f in directory.iterdir():
                assert "ROOT_SENTINEL" not in f.read_text()
            assert (directory / "api-secret-id").read_text() != (directory / "worker-secret-id").read_text()
            policies = [body["policy"] for path, body, _, _ in calls if path.startswith("sys/policies/acl/")]
            assert len(policies) == 2
            assert all('capabilities = ["update"]' in p and "rotate" not in p and "export" not in p for p in policies)

    def test_initialization_does_not_overwrite_recovery_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            d.chmod(0o700)
            (d / "ifora-openbao.json").write_text("{}")
            recovery = d / "operator-recovery.json"
            recovery.write_text("KEEP")
            with patch("sys.argv", ["setup", "init", "--directory", str(d)]), patch.object(setup, "request") as request:
                with self.assertRaises(RuntimeError):
                    setup.main()
                request.assert_not_called()
            assert recovery.read_text() == "KEEP"


if __name__ == "__main__":
    unittest.main()
