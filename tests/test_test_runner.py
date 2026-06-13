"""Tests for the test runner module."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from refactor_agent.config import AgentTestConfig
from refactor_agent.runners.test_runner import TestRunner


def _pytest_command() -> list[str]:
    """Return the pytest command that works in the current environment."""
    return [sys.executable, "-m", "pytest"]


@pytest.fixture
def test_config() -> AgentTestConfig:
    cmd = _pytest_command()
    return AgentTestConfig(command=cmd[0], args=cmd[1:] + ["-x"], timeout=60)


@pytest.fixture
def project_with_passing_tests(tmp_path: Path) -> Path:
    """Create a project with passing tests."""
    (tmp_path / "calc.py").write_text(textwrap.dedent("""\
        def add(a, b):
            return a + b

        def subtract(a, b):
            return a - b
    """), encoding="utf-8")

    (tmp_path / "test_calc.py").write_text(textwrap.dedent("""\
        from calc import add, subtract

        def test_add():
            assert add(2, 3) == 5

        def test_subtract():
            assert subtract(5, 3) == 2
    """), encoding="utf-8")

    return tmp_path


@pytest.fixture
def project_with_failing_tests(tmp_path: Path) -> Path:
    """Create a project with a failing test."""
    (tmp_path / "maths.py").write_text(textwrap.dedent("""\
        def broken_add(a, b):
            return a - b  # Bug!
    """), encoding="utf-8")

    (tmp_path / "test_maths.py").write_text(textwrap.dedent("""\
        from maths import broken_add

        def test_broken_add():
            assert broken_add(2, 3) == 5  # Will fail
    """), encoding="utf-8")

    return tmp_path


class TestTestRunner:
    def test_passing_tests(self, test_config: AgentTestConfig, project_with_passing_tests: Path):
        runner = TestRunner(test_config, project_with_passing_tests)
        result = runner.run()

        assert result.success is True
        assert result.return_code == 0
        assert result.timeout is False

    def test_failing_tests(self, test_config: AgentTestConfig, project_with_failing_tests: Path):
        runner = TestRunner(test_config, project_with_failing_tests)
        result = runner.run()

        assert result.success is False
        assert result.return_code != 0

    def test_no_tests_dir(self, test_config: AgentTestConfig, tmp_path: Path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        runner = TestRunner(test_config, tmp_path)
        result = runner.run()

        # Should handle gracefully (no tests collected = error code 4 in pytest)
        assert result.success is False

    def test_timeout(self, tmp_path: Path):
        config = AgentTestConfig(command="sleep", args=["10"], timeout=1)
        runner = TestRunner(config, tmp_path)
        result = runner.run()

        assert result.timeout is True
        assert result.success is False

    def test_command_not_found(self, tmp_path: Path):
        config = AgentTestConfig(command="nonexistent_test_runner_xyz", args=[])
        runner = TestRunner(config, tmp_path)
        result = runner.run()

        assert result.success is False
        assert "not found" in result.stderr.lower() or result.return_code == -1
