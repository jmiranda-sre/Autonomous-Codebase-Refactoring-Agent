"""Test Runner — executes test suites and validates results."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from refactor_agent.config import AgentTestConfig

logger = structlog.get_logger(__name__)


@dataclass
class TestExecuteResult:
    """Result of running a test suite."""

    success: bool
    return_code: int
    stdout: str
    stderr: str
    command: str
    timeout: bool = False


class TestRunner:
    """Executes project test suites and validates results."""

    def __init__(self, config: AgentTestConfig, project_path: Path) -> None:
        self.config = config
        self.project_path = project_path.resolve()

    def _detect_test_command(self) -> list[str]:
        """Auto-detect test command if not explicitly configured."""
        # Check for pytest
        pytest_ini = self.project_path / "pytest.ini"
        pyproject = self.project_path / "pyproject.toml"
        setup_cfg = self.project_path / "setup.cfg"

        if pytest_ini.exists() or pyproject.exists():
            return ["pytest"]

        # Check for unittest
        tests_dir = self.project_path / "tests"
        test_dir = self.project_path / "test"
        if tests_dir.exists() or test_dir.exists():
            return ["python", "-m", "unittest", "discover", "-s", "tests"]

        return [self.config.command]

    def run(self) -> TestExecuteResult:
        """Execute the test suite and return results."""
        cmd = self._detect_test_command()
        full_cmd = cmd + self.config.args

        logger.info("running_tests", command=" ".join(full_cmd), cwd=str(self.project_path))

        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_path),
                timeout=self.config.timeout,
            )
            success = proc.returncode == 0
            logger.info(
                "test_result",
                success=success,
                returncode=proc.returncode,
            )
            return TestExecuteResult(
                success=success,
                return_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                command=" ".join(full_cmd),
            )
        except subprocess.TimeoutExpired:
            logger.error("test_timeout", timeout=self.config.timeout)
            return TestExecuteResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Tests timed out after {self.config.timeout}s",
                command=" ".join(full_cmd),
                timeout=True,
            )
        except FileNotFoundError:
            logger.error("test_command_not_found", command=full_cmd[0])
            return TestExecuteResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Test command not found: {full_cmd[0]}",
                command=" ".join(full_cmd),
            )

    def run_specific(self, test_path: str) -> TestExecuteResult:
        """Run a specific test file or test function."""
        cmd = [self.config.command] + self.config.args + [test_path]

        logger.info("running_specific_test", command=" ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_path),
                timeout=self.config.timeout,
            )
            return TestExecuteResult(
                success=proc.returncode == 0,
                return_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                command=" ".join(cmd),
            )
        except subprocess.TimeoutExpired:
            return TestExecuteResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Test timed out after {self.config.timeout}s",
                command=" ".join(cmd),
                timeout=True,
            )
