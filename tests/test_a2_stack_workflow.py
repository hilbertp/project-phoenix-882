from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_UP_SCRIPT = REPO_ROOT / "scripts/stack_up.sh"
STACK_DOWN_SCRIPT = REPO_ROOT / "scripts/stack_down.sh"
STACK_SMOKE_CHECK_SCRIPT = REPO_ROOT / "scripts/stack_smoke_check.sh"
COMPOSE_FILE = REPO_ROOT / "infra/docker/docker-compose.yml"
DOCKER_INFO_TIMEOUT_SECONDS = 10
SCRIPT_TIMEOUT_SECONDS = 30
COMPOSE_TIMEOUT_SECONDS = 30


class A2StackWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker is required to run the local stack workflow tests")

        daemon_check = self._run_process(
            ["docker", "info"],
            timeout=DOCKER_INFO_TIMEOUT_SECONDS,
            timeout_context="docker info availability check",
        )
        if daemon_check.returncode != 0:
            self.skipTest("docker daemon is not available for local stack workflow tests")

        self._run_script(STACK_DOWN_SCRIPT, check=False)

    def tearDown(self) -> None:
        self._run_script(STACK_DOWN_SCRIPT, check=False)

    def test_local_stack_workflow_runs_start_smoke_and_stop_sequence(self) -> None:
        up_result = self._run_script(STACK_UP_SCRIPT)
        self.assertEqual(up_result.returncode, 0, up_result.stdout + up_result.stderr)

        smoke_result = self._run_script(STACK_SMOKE_CHECK_SCRIPT)
        self.assertEqual(smoke_result.returncode, 0, smoke_result.stdout + smoke_result.stderr)
        self.assertIn(
            "Local stack smoke check passed: api, worker, and postgres are running.",
            smoke_result.stdout,
        )

        down_result = self._run_script(STACK_DOWN_SCRIPT)
        self.assertEqual(down_result.returncode, 0, down_result.stdout + down_result.stderr)

        running_services = self._run_process(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "ps",
                "--status",
                "running",
                "--services",
            ],
            timeout=COMPOSE_TIMEOUT_SECONDS,
            timeout_context="post-shutdown running services check",
        )
        self.assertEqual(running_services.returncode, 0, running_services.stdout + running_services.stderr)
        self.assertEqual(running_services.stdout.strip(), "")

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

        if check and result.returncode != 0:
            self.fail(result.stdout + result.stderr)

        return result


if __name__ == "__main__":
    unittest.main()