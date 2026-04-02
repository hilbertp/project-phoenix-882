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
DOCKER_INFO_TIMEOUT_SECONDS = 10
SCRIPT_TIMEOUT_SECONDS = 30
COMPOSE_TIMEOUT_SECONDS = 30


class A2MountsAndEnvContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("docker is required to run the mount and env contract tests")

        daemon_check = self._run_process(
            ["docker", "info"],
            timeout=DOCKER_INFO_TIMEOUT_SECONDS,
            timeout_context="docker info availability check",
        )
        if daemon_check.returncode != 0:
            self.skipTest("docker daemon is not available for the mount and env contract tests")

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
        return self._run_process(
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
            timeout=COMPOSE_TIMEOUT_SECONDS,
            timeout_context=f"service command in {service}",
        )

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