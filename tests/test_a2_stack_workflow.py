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


class A2StackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is required to run the local stack workflow tests")

        daemon_check = subprocess.run(
            ["docker", "info"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if daemon_check.returncode != 0:
            raise unittest.SkipTest("docker daemon is not available for local stack workflow tests")

    def setUp(self) -> None:
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

        running_services = subprocess.run(
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
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(running_services.returncode, 0, running_services.stdout + running_services.stderr)
        self.assertEqual(running_services.stdout.strip(), "")

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

        if check and result.returncode != 0:
            self.fail(result.stdout + result.stderr)

        return result


if __name__ == "__main__":
    unittest.main()