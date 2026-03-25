from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class A1FoundationIntegrityTests(unittest.TestCase):
    def test_required_top_level_folders_exist(self) -> None:
        for relative_path in [
            "apps",
            "artifacts",
            "data",
            "docs",
            "infra",
            "scripts",
        ]:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_dir())

    def test_required_a1_files_exist(self) -> None:
        for relative_path in [
            "README.md",
            "pyproject.toml",
            ".env.example",
            "infra/docker/docker-compose.yml",
            "docs/repository_conventions.md",
            "docs/capability_a1_closure_review.md",
            "docs/capability_a2_closure_review.md",
            "scripts/format.sh",
            "scripts/lint.sh",
            "scripts/stack_up.sh",
            "scripts/stack_down.sh",
            "scripts/stack_smoke_check.sh",
        ]:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_file())

    def test_backend_scaffold_files_exist(self) -> None:
        for relative_path in [
            "apps/api/README.md",
            "apps/api/__init__.py",
            "apps/api/main.py",
            "apps/worker/README.md",
            "apps/worker/__init__.py",
            "apps/worker/main.py",
        ]:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_file())

    def test_ui_lane_does_not_contain_python_scaffold_files(self) -> None:
        ui_dir = REPO_ROOT / "apps/ui"

        self.assertFalse((ui_dir / "__init__.py").exists())
        self.assertFalse((ui_dir / "main.py").exists())
        self.assertEqual(list(ui_dir.glob("*.py")), [])

    def test_pyproject_contains_expected_ruff_baseline_signals(self) -> None:
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        ruff = pyproject["tool"]["ruff"]

        self.assertEqual(ruff["line-length"], 88)
        self.assertEqual(
            ruff["include"],
            ["apps/api/**/*.py", "apps/worker/**/*.py"],
        )
        self.assertEqual(
            ruff["extend-exclude"],
            ["apps/ui", "artifacts", "data", "docs", "infra", "scripts"],
        )
        self.assertEqual(ruff["lint"]["select"], ["E", "F", "I"])
        self.assertEqual(ruff["format"]["quote-style"], "double")
        self.assertEqual(ruff["format"]["indent-style"], "space")

    def test_env_example_documents_the_approved_local_runtime_contract(self) -> None:
        env_example = (REPO_ROOT / ".env.example").read_text().splitlines()
        env_lines = [
            line for line in env_example if line.strip() and not line.lstrip().startswith("#")
        ]

        entries: dict[str, str] = {}
        for line in env_lines:
            key, value = line.split("=", maxsplit=1)
            entries[key] = value

        self.assertEqual(
            set(entries),
            {
                "PHOENIX_POSTGRES_DB",
                "PHOENIX_POSTGRES_USER",
                "PHOENIX_POSTGRES_PASSWORD",
                "PHOENIX_DATABASE_URL",
                "PHOENIX_DATA_DIR",
                "PHOENIX_ARTIFACTS_DIR",
            },
        )
        self.assertEqual(entries["PHOENIX_POSTGRES_DB"], "phoenix")
        self.assertEqual(entries["PHOENIX_POSTGRES_USER"], "phoenix")
        self.assertEqual(entries["PHOENIX_DATA_DIR"], "/storage/data")
        self.assertEqual(entries["PHOENIX_ARTIFACTS_DIR"], "/storage/artifacts")
        self.assertIn("postgres:5432/phoenix", entries["PHOENIX_DATABASE_URL"])
        self.assertIn("phoenix-local-only", entries["PHOENIX_POSTGRES_PASSWORD"])
        self.assertIn("phoenix-local-only", entries["PHOENIX_DATABASE_URL"])

        for forbidden_key in ["AWS_ACCESS_KEY_ID", "SECRET_KEY", "OPENAI_API_KEY"]:
            with self.subTest(forbidden_key=forbidden_key):
                self.assertNotIn(forbidden_key, entries)

    def test_compose_runtime_shell_contains_expected_a2_signals(self) -> None:
        compose_file = (REPO_ROOT / "infra/docker/docker-compose.yml").read_text()

        for expected_signal in [
            "services:",
            "  api:",
            "  worker:",
            "  postgres:",
            "../../apps/api:/workspace/apps/api",
            "../../apps/worker:/workspace/apps/worker",
            "../../data:/storage/data",
            "../../artifacts:/storage/artifacts",
            "postgres_data:/var/lib/postgresql/data",
            "PHOENIX_SERVICE_ROLE: api",
            "PHOENIX_SERVICE_ROLE: worker",
            "PHOENIX_DATABASE_URL:",
            "PHOENIX_DATA_DIR:",
            "PHOENIX_ARTIFACTS_DIR:",
            "POSTGRES_DB:",
            "POSTGRES_USER:",
            "POSTGRES_PASSWORD:",
        ]:
            with self.subTest(expected_signal=expected_signal):
                self.assertIn(expected_signal, compose_file)

    def test_workflow_scripts_target_backend_paths(self) -> None:
        format_script = (REPO_ROOT / "scripts/format.sh").read_text()
        lint_script = (REPO_ROOT / "scripts/lint.sh").read_text()

        self.assertIn("ruff format apps/api apps/worker", format_script)
        self.assertIn("ruff check apps/api apps/worker", lint_script)

    def test_local_stack_workflow_scripts_cover_expected_services(self) -> None:
        stack_up = (REPO_ROOT / "scripts/stack_up.sh").read_text()
        stack_down = (REPO_ROOT / "scripts/stack_down.sh").read_text()
        smoke_check = (REPO_ROOT / "scripts/stack_smoke_check.sh").read_text()

        self.assertIn('docker compose -f "$COMPOSE_FILE" up -d', stack_up)
        self.assertIn('docker compose -f "$COMPOSE_FILE" down', stack_down)
        self.assertIn("docker compose -f \"$COMPOSE_FILE\" ps --status running --services", smoke_check)

        for service in ["api", "worker", "postgres"]:
            with self.subTest(service=service):
                self.assertIn(service, smoke_check)

    def test_root_readme_contains_expected_onboarding_anchors(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text()

        for anchor in [
            "# Project Phoenix",
            "## Start Here",
            "docs/repository_conventions.md",
            "## Top-Level Structure",
            "## Current A1 Foundation Status",
            "## Not Fully Built Yet",
        ]:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, readme)


if __name__ == "__main__":
    unittest.main()
