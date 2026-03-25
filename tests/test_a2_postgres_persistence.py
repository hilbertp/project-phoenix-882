from __future__ import annotations

import shutil
import subprocess
import time
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_UP_SCRIPT = REPO_ROOT / "scripts/stack_up.sh"
STACK_DOWN_SCRIPT = REPO_ROOT / "scripts/stack_down.sh"
COMPOSE_FILE = REPO_ROOT / "infra/docker/docker-compose.yml"
POSTGRES_SERVICE = "postgres"
POSTGRES_DB = "phoenix"
POSTGRES_USER = "phoenix"
TEST_TABLE = "a2_s3_persistence_check"


class A2PostgresPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is required to run the PostgreSQL persistence test")

        daemon_check = subprocess.run(
            ["docker", "info"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if daemon_check.returncode != 0:
            raise unittest.SkipTest("docker daemon is not available for the PostgreSQL persistence test")

    def setUp(self) -> None:
        self._run_script(STACK_DOWN_SCRIPT, check=False)

    def tearDown(self) -> None:
        self._run_script(STACK_DOWN_SCRIPT, check=False)

    def test_postgres_value_survives_service_recreation(self) -> None:
        self._run_script(STACK_UP_SCRIPT)
        self._wait_for_postgres_ready()

        test_key = f"persistence-{uuid.uuid4().hex}"
        stored_value = f"stored-{uuid.uuid4().hex}"

        self._run_psql(
            f"CREATE TABLE IF NOT EXISTS {TEST_TABLE} ("
            "test_key TEXT PRIMARY KEY, "
            "stored_value TEXT NOT NULL"
            ");"
        )
        self._run_psql(
            "INSERT INTO "
            f"{TEST_TABLE} (test_key, stored_value) VALUES ('{test_key}', '{stored_value}');"
        )

        recreate_result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "up",
                "-d",
                "--force-recreate",
                "--no-deps",
                POSTGRES_SERVICE,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(recreate_result.returncode, 0, recreate_result.stdout + recreate_result.stderr)

        self._wait_for_postgres_ready()

        query_result = self._run_psql(
            f"SELECT stored_value FROM {TEST_TABLE} WHERE test_key = '{test_key}';"
        )
        self.assertEqual(query_result.stdout.strip(), stored_value)

        self._run_psql(f"DELETE FROM {TEST_TABLE} WHERE test_key = '{test_key}';")

    def _wait_for_postgres_ready(self) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready_result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE_FILE),
                    "exec",
                    "-T",
                    POSTGRES_SERVICE,
                    "pg_isready",
                    "-U",
                    POSTGRES_USER,
                    "-d",
                    POSTGRES_DB,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if ready_result.returncode == 0:
                return
            time.sleep(1)

        self.fail("postgres did not become ready in time")

    def _run_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "exec",
                "-T",
                POSTGRES_SERVICE,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                POSTGRES_USER,
                "-d",
                POSTGRES_DB,
                "-t",
                "-A",
                "-c",
                sql,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def _run_script(
        self,
        script_path: Path,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(script_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        return result


if __name__ == "__main__":
    unittest.main()