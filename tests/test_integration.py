"""Integration test — full workflow with mocked LLM and git."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import git
import pytest

from refactor_agent.config import AgentConfig, LLMConfig, ScanConfig, RefactorConfig, GitConfig, AgentTestConfig, ReportConfig
from refactor_agent.orchestrator import RefactorOrchestrator
from refactor_agent.llm.client import LLMResponse


@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    """Create a mock project with legacy code and passing tests."""
    # Initialize Git
    repo = git.Repo.init(str(tmp_path))

    # Legacy code
    (tmp_path / "legacy.py").write_text(textwrap.dedent("""\
        def bloated(a, b, c, d, e, f, g, h):
            x = 1
            y = 2
            z = 3
            if a:
                if b:
                    if c:
                        for i in range(100):
                            if d:
                                x += i
                            elif e:
                                y += i
                            else:
                                z += i
            return x + y + z
    """), encoding="utf-8")

    # Passing test
    (tmp_path / "test_legacy.py").write_text(textwrap.dedent("""\
        from legacy import bloated

        def test_bloated():
            assert bloated(1, 1, 1, 1, 0, 0, 0, 0) > 0
    """), encoding="utf-8")

    repo.index.add(["legacy.py", "test_legacy.py"])
    repo.index.commit("Initial commit")
    return tmp_path


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        llm=LLMConfig(endpoint="http://localhost:11434", model="test-model", timeout=10),
        scan=ScanConfig(),
        refactor=RefactorConfig(
            max_function_lines=5,
            max_function_params=3,
            max_cyclomatic_complexity=3,
        ),
        git=GitConfig(branch_prefix="refactor/test", auto_branch=True, commit_on_pass=True, discard_on_fail=True),
        test=AgentTestConfig(command="pytest", args=["-x"], timeout=30),
        report=ReportConfig(format="json", output_dir="reports"),
    )


class TestOrchestratorIntegration:
    @patch("refactor_agent.llm.client.LLMClient.refactor_function")
    def test_full_workflow_success(self, mock_refactor, mock_project: Path, agent_config: AgentConfig):
        # Mock LLM to return a valid refactored function
        mock_refactor.return_value = LLMResponse(
            raw="```python\ndef bloated(a: int, b: int) -> int:\n    return a + b\n```",
            refactored_code="def bloated(a: int, b: int) -> int:\n    return a + b",
            is_valid_python=True,
            error=None,
        )

        # Update test to match the refactored function signature
        # The refactored function changes the signature, so tests need to be adapted
        # For this test, let's make the refactored code preserve the signature
        mock_refactor.return_value = LLMResponse(
            raw="```python\ndef bloated(a, b, c, d, e, f, g, h):\n    return sum([a,b,c,d,e,f,g,h])\n```",
            refactored_code="def bloated(a, b, c, d, e, f, g, h):\n    return sum([a,b,c,d,e,f,g,h])",
            is_valid_python=True,
            error=None,
        )

        agent_config.report.output_dir = str(mock_project / "reports")
        orchestrator = RefactorOrchestrator(agent_config, mock_project)
        report = orchestrator.run()

        assert report.files_scanned >= 1
        assert report.functions_identified >= 1

    @patch("refactor_agent.llm.client.LLMClient.refactor_function")
    def test_workflow_with_invalid_llm_output(self, mock_refactor, mock_project: Path, agent_config: AgentConfig):
        # Mock LLM to return invalid Python
        mock_refactor.return_value = LLMResponse(
            raw="```python\ndef bloated(:\n    pass\n```",
            refactored_code="def bloated(:\n    pass",
            is_valid_python=False,
            error="LLM output failed Python syntax validation",
        )

        agent_config.report.output_dir = str(mock_project / "reports")
        orchestrator = RefactorOrchestrator(agent_config, mock_project)
        report = orchestrator.run()

        # Nothing should be applied
        assert report.total_refactorings_applied == 0
