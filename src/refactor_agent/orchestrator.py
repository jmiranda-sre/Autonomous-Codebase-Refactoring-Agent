"""Orchestrator — main engine that ties AST analysis, LLM, Git, and tests together."""

from __future__ import annotations

from pathlib import Path

import structlog

from refactor_agent.config import AgentConfig
from refactor_agent.analyzers.ast_analyzer import ASTAnalyzer, FileAnalysis
from refactor_agent.llm.client import LLMClient, LLMResponse
from refactor_agent.git_utils.workflow import GitWorkflow, GitWorkflowError
from refactor_agent.runners.test_runner import TestRunner, TestExecuteResult
from refactor_agent.reports.generator import (
    ReportGenerator,
    AgentReport,
    RefactoringOperation,
)

logger = structlog.get_logger(__name__)


class RefactorOrchestrator:
    """Main orchestrator for the autonomous refactoring workflow."""

    def __init__(self, config: AgentConfig, target_dir: Path) -> None:
        self.config = config
        self.target_dir = target_dir.resolve()

        self.analyzer = ASTAnalyzer(config.scan, config.refactor)
        self.llm_client = LLMClient(config.llm)
        self.git = GitWorkflow(self.target_dir, config.git)
        self.test_runner = TestRunner(config.test, self.target_dir)
        self.report_gen = ReportGenerator(config.report)
        self.report: AgentReport = self.report_gen.create_report()

    def run(self) -> AgentReport:
        """Execute the full refactoring workflow."""
        logger.info("orchestrator_start", target=str(self.target_dir))
        self.report.repository_path = str(self.target_dir)

        # Phase 1: Scan and analyze
        logger.info("phase_1_scan", status="starting")
        analyses = self.analyzer.analyze_repository(self.target_dir)
        self.report_gen.record_scan_results(self.report, analyses)
        logger.info(
            "phase_1_scan",
            status="complete",
            files=self.report.files_scanned,
            functions=self.report.functions_identified,
            classes=self.report.classes_identified,
        )

        if not analyses:
            logger.warning("no_python_files_found")
            self.report.errors.append("No Python files found in target directory")
            return self._finalize()

        # Check if there are candidates
        total_candidates = sum(
            len(a.function_candidates) + len(a.class_candidates) for a in analyses
        )
        if total_candidates == 0:
            logger.info("no_refactoring_candidates")
            return self._finalize()

        # Phase 2: Create safety branch
        logger.info("phase_2_branch", status="starting")
        try:
            branch_name = self.git.create_refactor_branch()
            logger.info("phase_2_branch", status="complete", branch=branch_name)
        except GitWorkflowError as exc:
            logger.error("branch_creation_failed", error=str(exc))
            self.report.errors.append(f"Git branch creation failed: {exc}")
            return self._finalize()
        except Exception as exc:
            logger.error("unexpected_git_error", error=str(exc))
            self.report.errors.append(f"Unexpected Git error: {exc}")
            return self._finalize()

        # Phase 3: Refactor each candidate
        logger.info("phase_3_refactor", status="starting")
        all_passed = True

        for analysis in analyses:
            # Process function candidates
            for func_candidate in analysis.function_candidates:
                success = self._process_candidate(
                    candidate_type="function",
                    name=func_candidate.name,
                    file_path=func_candidate.file_path,
                    start_line=func_candidate.start_line,
                    end_line=func_candidate.end_line,
                    source=func_candidate.source,
                    violations=func_candidate.violations,
                    refactor_fn=lambda c=func_candidate: self.llm_client.refactor_function(c),
                )
                if not success:
                    all_passed = False

            # Process class candidates
            for class_candidate in analysis.class_candidates:
                success = self._process_candidate(
                    candidate_type="class",
                    name=class_candidate.name,
                    file_path=class_candidate.file_path,
                    start_line=class_candidate.start_line,
                    end_line=class_candidate.end_line,
                    source=class_candidate.source,
                    violations=class_candidate.violations,
                    refactor_fn=lambda c=class_candidate: self.llm_client.refactor_class(c),
                )
                if not success:
                    all_passed = False

                # Also process individual methods within the class
                for method_candidate in class_candidate.methods:
                    success = self._process_candidate(
                        candidate_type="function",
                        name=f"{class_candidate.name}.{method_candidate.name}",
                        file_path=method_candidate.file_path,
                        start_line=method_candidate.start_line,
                        end_line=method_candidate.end_line,
                        source=method_candidate.source,
                        violations=method_candidate.violations,
                        refactor_fn=lambda c=method_candidate: self.llm_client.refactor_function(c),
                    )
                    if not success:
                        all_passed = False

        # Phase 4: Run tests and decide commit/rollback
        logger.info("phase_4_validation", status="starting")
        test_result = self.test_runner.run()

        if test_result.success and all_passed:
            self._handle_success(test_result)
        else:
            self._handle_failure(test_result)

        logger.info("phase_4_validation", status="complete")
        return self._finalize()

    def _process_candidate(
        self,
        candidate_type: str,
        name: str,
        file_path: Path,
        start_line: int,
        end_line: int,
        source: str,
        violations: list[str],
        refactor_fn,
    ) -> bool:
        """Process a single refactoring candidate. Returns True if successful."""
        operation = RefactoringOperation(
            candidate_type=candidate_type,
            candidate_name=name,
            file_path=str(file_path),
            start_line=start_line,
            end_line=end_line,
            violations=violations,
            original_source=source,
        )

        try:
            # Call LLM
            logger.info("refactoring", type=candidate_type, name=name)
            llm_response: LLMResponse = refactor_fn()

            operation.prompt_sent = "(see LLM request log)"
            operation.llm_raw_response = llm_response.raw[:2000]  # Truncate for report
            operation.llm_refactored_code = llm_response.refactored_code or ""
            operation.llm_valid_syntax = llm_response.is_valid_python
            operation.llm_error = llm_response.error

            if not llm_response.refactored_code or not llm_response.is_valid_python:
                logger.warning(
                    "refactoring_skipped",
                    name=name,
                    reason=llm_response.error or "No code extracted from LLM response",
                )
                operation.applied = False
                self.report_gen.add_operation(self.report, operation)
                return False

            # Apply refactoring
            self.git.apply_refactoring(file_path, start_line, end_line, llm_response.refactored_code)
            operation.applied = True

        except Exception as exc:
            logger.error("refactoring_failed", name=name, error=str(exc))
            operation.error = str(exc)
            operation.applied = False
            self.report_gen.add_operation(self.report, operation)
            return False

        self.report_gen.add_operation(self.report, operation)
        return True

    def _handle_success(self, test_result: TestExecuteResult) -> None:
        """Handle case where all tests pass — commit changes."""
        # Update all operations with test result
        for op in self.report.operations:
            op.test_result = test_result
            if op.applied:
                op.committed = True

        if self.config.git.commit_on_pass:
            commit_msg = self._build_commit_message()
            self.git.commit_all_changes(commit_msg)

            for op in self.report.operations:
                if op.applied:
                    op.commit_message = commit_msg

        self.git.switch_to_original()
        logger.info("refactoring_committed", committed=self.report.total_refactorings_applied)

    def _handle_failure(self, test_result: TestExecuteResult) -> None:
        """Handle case where tests fail — rollback changes."""
        for op in self.report.operations:
            op.test_result = test_result
            op.committed = False

        try:
            self.git.rollback()
            logger.info("refactoring_rolled_back")
        except Exception as exc:
            logger.error("rollback_failed", error=str(exc))
            self.report.errors.append(f"Rollback failed: {exc}")

    def _build_commit_message(self) -> str:
        """Build a conventional commit message for the refactoring."""
        names = [op.candidate_name for op in self.report.operations if op.applied]
        if len(names) == 1:
            return f"refactor: auto-refactor `{names[0]}` via LLM agent"
        elif len(names) <= 3:
            return f"refactor: auto-refactor {', '.join(f'`{n}`' for n in names)} via LLM agent"
        else:
            return f"refactor: auto-refactor {len(names)} candidates via LLM agent"

    def _finalize(self) -> AgentReport:
        """Finalize report and save to disk."""
        self.report_gen.finalize_report(self.report)
        report_path = self.report_gen.save_report(self.report)
        logger.info("report_saved", path=str(report_path))

        self.llm_client.close()
        return self.report
