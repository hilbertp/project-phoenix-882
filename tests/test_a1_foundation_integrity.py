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
            "docs/repository_conventions.md",
            "docs/capability_a1_closure_review.md",
            "scripts/format.sh",
            "scripts/lint.sh",
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

    def test_env_example_stays_minimal_and_non_speculative(self) -> None:
        env_example = (REPO_ROOT / ".env.example").read_text()

        self.assertEqual(
            env_example,
            "# Copy this file to .env or .env.local for local-only values.\n"
            "# Do not commit real secrets.\n",
        )

    def test_workflow_scripts_target_backend_paths(self) -> None:
        format_script = (REPO_ROOT / "scripts/format.sh").read_text()
        lint_script = (REPO_ROOT / "scripts/lint.sh").read_text()

        self.assertIn("ruff format apps/api apps/worker", format_script)
        self.assertIn("ruff check apps/api apps/worker", lint_script)

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
