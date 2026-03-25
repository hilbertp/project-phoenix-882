from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_UP_SCRIPT = REPO_ROOT / "scripts/stack_up.sh"
STACK_DOWN_SCRIPT = REPO_ROOT / "scripts/stack_down.sh"
COMPOSE_FILE = REPO_ROOT / "infra/docker/docker-compose.yml"
EXPECTED_MOUNTS = ["/storage/data", "/storage/artifacts"]
EXPECTED_ENV_BY_SERVICE = {
    "api": {
        "PHOENIX_SERVICE_ROLE": "api",
        "PHOENIX_DATABASE_URL": "postgresql://phoenix:phoenix-local-only@postgres:5432/phoenix",
        "PHOENIX_DATA_DIR": "/storage/data",
        "PHOENIX_ARTIFACTS_DIR": "/storage/artifacts",
    },
    "worker": {
        "PHOENIX_SERVICE_ROLE": "worker",
        "PHOENIX_DATABASE_URL": "postgresql://phoenix:phoenix-local-only@postgres:5432/phoenix",
        "PHOENIX_DATA_DIR": "/storage/data",
        "PHOENIX_ARTIFACTS_DIR": "/storage/artifacts",
    },
}


class A2MountsAndEnvContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is required to run the mount and env contract tests")

        daemon_check = subprocess.run(
            ["docker", "info"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if daemon_check.returncode != 0:
            raise unittest.SkipTest("docker daemon is not available for the mount and env contract tests")

    def setUp(self) -> None:
        self._run_script(STACK_DOWN_SCRIPT, check=False)
        self._run_script(STACK_UP_SCRIPT)

    def tearDown(self) -> None:
        self._run_script(STACK_DOWN_SCRIPT, check=False)

    def test_compute_containers_expose_expected_storage_mounts(self) -> None:
        for service in ["api", "worker"]:
            for mount_path in EXPECTED_MOUNTS:
                with self.subTest(service=service, mount_path=mount_path):
                    result = self._run_in_service(service, ["test", "-d", mount_path])
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compute_containers_expose_expected_runtime_env_contract(self) -> None:
        for service, expected_env in EXPECTED_ENV_BY_SERVICE.items():
            for env_name, expected_value in expected_env.items():
                with self.subTest(service=service, env_name=env_name):
                    result = self._run_in_service(
                        service,
                        ["sh", "-c", f'printf "%s" "${env_name}"'],
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, expected_value)

    def _run_in_service(
        self,
        service: str,
        command: list[str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "exec",
                "-T",
                service,
                *command,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

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