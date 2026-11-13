"""scripts/backup.sh and scripts/restore.sh against throwaway PostgreSQL containers (IFORA-21).

Needs a reachable Docker daemon and the postgres:16-alpine image; skipped otherwise (the Drone test step has no
Docker socket). Uses a small synthetic schema: the real-schema drill is documented in the README.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:16-alpine"


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        ok = subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
        return ok and subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


SCHEMA = """
CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES ('0099');
CREATE TABLE tenants (id serial PRIMARY KEY, name text);
CREATE TABLE users (id serial PRIMARY KEY, email text, first_name text);
CREATE TABLE groups (id serial PRIMARY KEY, name text);
CREATE TABLE applications (id serial PRIMARY KEY, name text);
CREATE TABLE application_assignments (id serial PRIMARY KEY, app_id int);
INSERT INTO tenants (name) VALUES ('default');
INSERT INTO users (email, first_name) SELECT 'u' || i || '@example.com', 'First' || i FROM generate_series(1, 7) i;
INSERT INTO groups (name) VALUES ('g1'), ('g2');
"""


@unittest.skipUnless(docker_ready(), "Docker or the postgres:16-alpine image is not available")
class BackupRestore(unittest.TestCase):
    @classmethod
    def start(cls, tag):
        name = f"ifora-bk-test-{tag}-{uuid.uuid4().hex[:8]}"
        subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_USER=ifora", "-e", "POSTGRES_PASSWORD=x",
                        "-e", "POSTGRES_DB=ifora", "--tmpfs", "/var/lib/postgresql/data", IMAGE],
                       check=True, capture_output=True)
        cls.addClassCleanup(subprocess.run, ["docker", "rm", "-f", name], capture_output=True)
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "psql", "-U", "ifora", "-d", "ifora", "-Atc", "select 1"],
                              capture_output=True).returncode == 0:
                return name
            time.sleep(1)
        raise RuntimeError(f"{name} did not become ready")

    @classmethod
    def setUpClass(cls):
        cls.src = cls.start("src")
        cls.dst = cls.start("dst")
        cls.work = Path(tempfile.mkdtemp(prefix="ifora-bk-test-"))
        cls.addClassCleanup(shutil.rmtree, cls.work, True)
        cls.sql(cls.src, SCHEMA)
        r = cls.script("backup.sh", container=cls.src)
        assert r.returncode == 0, r.stderr + r.stdout
        cls.dump = next(cls.work.glob("ifora-*.dump"))
        cls.manifest = cls.dump.with_suffix(".manifest")

    @classmethod
    def sql(cls, container, sql):
        r = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", "ifora", "-d", "ifora", "-X", "-v", "ON_ERROR_STOP=1", "-Atq"],
                           input=sql, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    @classmethod
    def script(cls, name, *args, container, directory=None):
        env = {**os.environ, "IFORA_PG_CONTAINER": container, "IFORA_BACKUP_DIR": str(directory or cls.work)}
        return subprocess.run([str(ROOT / "scripts" / name), *args], capture_output=True, text=True, env=env, cwd=ROOT)

    def reset_dst(self):
        self.sql(self.dst, "DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

    def tables(self, container):
        return self.sql(container, "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")

    def test_backup_files_are_private_and_describe_the_dump(self):
        self.assertEqual(oct(self.dump.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(self.manifest.stat().st_mode & 0o777), "0o600")
        text = self.manifest.read_text()
        for line in ("alembic_version=0099", "count.users=7", "count.groups=2", "count.tenants=1",
                     "count.applications=0", "counts_stable=true"):
            self.assertIn(line, text)

    def test_backup_refuses_a_directory_inside_the_checkout(self):
        inside = ROOT / "backend" / ".backup-test-tmp"
        try:
            r = self.script("backup.sh", container=self.src, directory=inside)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("inside the checkout", r.stderr)
            self.assertEqual(list(inside.glob("*.dump")) if inside.exists() else [], [])
        finally:
            shutil.rmtree(inside, ignore_errors=True)

    def test_restore_into_empty_target_then_refuses_then_force(self):
        self.reset_dst()
        r = self.script("restore.sh", str(self.dump), container=self.dst)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("restored and verified", r.stdout)
        self.assertEqual(self.sql(self.dst, "SELECT count(*) FROM users"), "7")
        again = self.script("restore.sh", str(self.dump), container=self.dst)
        self.assertEqual(again.returncode, 1)
        self.assertIn("already has", again.stderr)
        forced = self.script("restore.sh", str(self.dump), "--force", container=self.dst)
        self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)

    def test_tampered_dump_is_refused_before_touching_the_target(self):
        self.reset_dst()
        bad = self.work / "tampered.dump"
        bad.write_bytes(self.dump.read_bytes() + b"x")
        shutil.copy(self.manifest, self.work / "tampered.manifest")
        r = self.script("restore.sh", str(bad), container=self.dst)
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum mismatch", r.stderr)
        self.assertEqual(self.tables(self.dst), "0")

    def test_missing_manifest_needs_an_explicit_flag(self):
        self.reset_dst()
        lone = self.work / "lone.dump"
        shutil.copy(self.dump, lone)
        r = self.script("restore.sh", str(lone), container=self.dst)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--skip-checksum", r.stderr)
        self.assertEqual(self.tables(self.dst), "0")

    def test_failure_midway_rolls_back_and_leaves_the_target_unchanged(self):
        self.reset_dst()
        self.sql(self.dst, SCHEMA)
        self.sql(self.dst, "UPDATE users SET first_name='MARKER' WHERE id=1; CREATE VIEW blocks_drop AS SELECT id FROM users;")
        before = self.tables(self.dst)
        r = self.script("restore.sh", str(self.dump), "--force", container=self.dst)  # DROP TABLE users fails: view depends on it
        self.assertEqual(r.returncode, 1)
        self.assertIn("rolled back", r.stderr)
        self.assertEqual(self.tables(self.dst), before)
        self.assertEqual(self.sql(self.dst, "SELECT count(*) FROM users WHERE first_name='MARKER'"), "1")

    def test_count_mismatch_after_restore_is_reported(self):
        self.reset_dst()
        edited = self.work / "edited.manifest"
        edited.write_text(self.manifest.read_text().replace("count.users=7", "count.users=8"))
        shutil.copy(self.dump, self.work / "edited.dump")
        r = self.script("restore.sh", str(self.work / "edited.dump"), container=self.dst)
        self.assertEqual(r.returncode, 3, r.stderr + r.stdout)
        self.assertIn("MISMATCH", r.stdout)


if __name__ == "__main__":
    unittest.main()
