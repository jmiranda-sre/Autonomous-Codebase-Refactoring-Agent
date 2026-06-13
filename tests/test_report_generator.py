"""Tests for the report generator module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refactor_agent.config import ReportConfig
from refactor_agent.reports.generator import (
    ReportGenerator,
    AgentReport,
    RefactoringOperation,
)
from refactor_agent.runners.test_runner import TestExecuteResult


@pytest.fixture
def report_config(tmp_path: Path) -> ReportConfig:
    return ReportConfig(format="json", output_dir=str(tmp_path / "reports"), save_prompts=True)


@pytest.fixture
def sample_report() -> AgentReport:
    report = AgentReport(
        repository_path="/tmp/test-repo",
        files_scanned=5,
        functions_identified=3,
        classes_identified=1,
    )
    report.operations.append(RefactoringOperation(
        candidate_type="function",
        candidate_name="bloated_func",
        file_path="src/module.py",
        start_line=1,
        end_line=30,
        violations=["FUNCTION_TOO_LONG: 30 lines (max 10)"],
        original_source="def bloated_func(a, b, c): ...",
        llm_refactored_code="def bloated_func(a): ...",
        llm_valid_syntax=True,
        applied=True,
        test_result=TestExecuteResult(success=True, return_code=0, stdout="OK", stderr="", command="pytest"),
        committed=True,
        commit_message="refactor: auto-refactor `bloated_func` via LLM agent",
    ))
    report.operations.append(RefactoringOperation(
        candidate_type="class",
        candidate_name="BigClass",
        file_path="src/big.py",
        start_line=1,
        end_line=200,
        violations=["TOO_MANY_METHODS: 12 (max 5)"],
        original_source="class BigClass: ...",
        llm_valid_syntax=False,
        applied=False,
        llm_error="LLM output failed Python syntax validation",
    ))
    return report


class TestReportGenerator:
    def test_create_report(self, report_config: ReportConfig):
        gen = ReportGenerator(report_config)
        report = gen.create_report()
        assert isinstance(report, AgentReport)
        assert report.files_scanned == 0

    def test_finalize_report(self, report_config: ReportConfig, sample_report: AgentReport):
        gen = ReportGenerator(report_config)
        gen.finalize_report(sample_report)
        assert sample_report.total_refactorings_applied == 1
        assert sample_report.total_refactorings_committed == 1
        assert sample_report.total_refactorings_rolled_back == 0

    def test_save_json_report(self, report_config: ReportConfig, sample_report: AgentReport):
        gen = ReportGenerator(report_config)
        gen.finalize_report(sample_report)
        path = gen.save_report(sample_report)

        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["repository_path"] == "/tmp/test-repo"
        assert data["files_scanned"] == 5
        assert len(data["operations"]) == 2

    def test_save_markdown_report(self, tmp_path: Path, sample_report: AgentReport):
        config = ReportConfig(format="md", output_dir=str(tmp_path / "reports"))
        gen = ReportGenerator(config)
        gen.finalize_report(sample_report)
        path = gen.save_report(sample_report)

        content = path.read_text(encoding="utf-8")
        assert "# Refactoring Agent Report" in content
        assert "bloated_func" in content
        assert "BigClass" in content

    def test_save_text_report(self, tmp_path: Path, sample_report: AgentReport):
        config = ReportConfig(format="txt", output_dir=str(tmp_path / "reports"))
        gen = ReportGenerator(config)
        gen.finalize_report(sample_report)
        path = gen.save_report(sample_report)

        content = path.read_text(encoding="utf-8")
        assert "REFACTORING AGENT REPORT" in content
        assert "bloated_func" in content
