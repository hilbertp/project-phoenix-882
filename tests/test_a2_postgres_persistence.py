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
DOCKER_INFO_TIMEOUT_SECONDS = 10
SCRIPT_TIMEOUT_SECONDS = 30
COMPOSE_TIMEOUT_SECONDS = 30
POSTGRES_READY_COMMAND_TIMEOUT_SECONDS = 10


class A2PostgresPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker is required to run the PostgreSQL persistence test")

        daemon_check = self._run_process(
            ["docker", "info"],
            timeout=DOCKER_INFO_TIMEOUT_SECONDS,
            timeout_context="docker info availability check",
        )
        if daemon_check.returncode != 0:
            self.skipTest("docker daemon is not available for the PostgreSQL persistence test")

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

        recreate_result = self._run_process(
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
            timeout=COMPOSE_TIMEOUT_SECONDS,
            timeout_context="postgres service recreation",
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
            ready_result = self._run_process(
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
                timeout=POSTGRES_READY_COMMAND_TIMEOUT_SECONDS,
                timeout_context="postgres readiness check",
            )
            if ready_result.returncode == 0:
                return
            time.sleep(1)

        self.fail("postgres did not become ready in time")

    def _run_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        result = self._run_process(
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
            timeout=COMPOSE_TIMEOUT_SECONDS,
            timeout_context="postgres psql command",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def _run_process(
        self,
        command: list[str],
        *,
        timeout: int,
        timeout_context: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            self.fail(
                f"Timed out after {timeout}s during {timeout_context}.\n"
                f"Command: {' '.join(command)}\n"
                f"stdout: {stdout}\n"
                f"stderr: {stderr}"
            )

    def _run_script(
        self,
        script_path: Path,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = self._run_process(
            [str(script_path)],
            timeout=SCRIPT_TIMEOUT_SECONDS,
            timeout_context=f"script {script_path.name}",
        )

        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        return result


if __name__ == "__main__":
    unittest.main()