"""Git Workflow — safe branch creation, conditional commit, and rollback."""

from __future__ import annotations

import time
from pathlib import Path

import git
import structlog

from refactor_agent.config import GitConfig

logger = structlog.get_logger(__name__)


class GitWorkflowError(Exception):
    """Raised when a Git operation fails."""


class GitWorkflow:
    """Manages Git operations for safe refactoring workflow."""

    def __init__(self, repo_path: Path, config: GitConfig) -> None:
        self.repo_path = repo_path.resolve()
        self.config = config
        self._repo: git.Repo | None = None
        self._original_branch: str | None = None
        self._refactor_branch: str | None = None

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            try:
                self._repo = git.Repo(str(self.repo_path))
            except git.InvalidGitRepositoryError:
                raise GitWorkflowError(f"Not a Git repository: {self.repo_path}")
            except git.NoSuchPathError:
                raise GitWorkflowError(f"Path does not exist: {self.repo_path}")
        return self._repo

    @property
    def current_branch(self) -> str:
        return self.repo.active_branch.name

    def _generate_branch_name(self) -> str:
        timestamp = int(time.time())
        return f"{self.config.branch_prefix}-{timestamp}"

    def create_refactor_branch(self) -> str:
        """Create a new branch for refactoring. Returns branch name."""
        if not self.config.auto_branch:
            logger.info("auto_branch_disabled", staying_on=self.current_branch)
            return self.current_branch

        self._original_branch = self.current_branch
        branch_name = self._generate_branch_name()

        # Ensure working tree is clean
        if self.repo.is_dirty(untracked_files=True):
            raise GitWorkflowError(
                "Working tree has uncommitted changes. "
                "Commit or stash before running the agent."
            )

        self.repo.create_head(branch_name)
        self.repo.heads[branch_name].checkout()
        self._refactor_branch = branch_name

        logger.info(
            "branch_created",
            branch=branch_name,
            original_branch=self._original_branch,
        )
        return branch_name

    def apply_refactoring(self, file_path: Path, start_line: int, end_line: int, new_code: str) -> None:
        """Apply refactored code to a file by replacing the specified line range."""
        abs_path = self.repo_path / file_path if not file_path.is_absolute() else file_path
        source = abs_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)

        # Replace lines (1-indexed to 0-indexed)
        new_lines = lines[: start_line - 1] + [new_code + "\n"] + lines[end_line:]

        abs_path.write_text("".join(new_lines), encoding="utf-8")
        logger.info(
            "refactoring_applied",
            file=str(abs_path),
            lines=f"{start_line}-{end_line}",
        )

    def stage_and_commit(self, file_path: Path, message: str) -> None:
        """Stage a file and commit with a descriptive message."""
        abs_path = self.repo_path / file_path if not file_path.is_absolute() else file_path

        self.repo.index.add([str(abs_path.relative_to(self.repo_path))])
        self.repo.index.commit(message)

        logger.info("committed", file=str(file_path), message=message)

    def commit_all_changes(self, message: str) -> None:
        """Stage all modified files and commit."""
        self.repo.git.add("-A")
        self.repo.index.commit(message)
        logger.info("committed_all", message=message)

    def rollback(self) -> None:
        """Discard changes and return to the original branch."""
        # Restore original files
        self.repo.git.checkout("--", ".")

        # Switch back to original branch
        if self._original_branch and self._refactor_branch:
            self.repo.heads[self._original_branch].checkout()

            # Delete refactor branch if configured
            if self.config.discard_on_fail:
                self.repo.delete_head(self._refactor_branch, force=True)
                logger.info(
                    "branch_deleted",
                    branch=self._refactor_branch,
                )
            else:
                logger.info(
                    "branch_kept_for_inspection",
                    branch=self._refactor_branch,
                )

        logger.info("rollback_complete", original_branch=self._original_branch)

    def switch_to_original(self) -> None:
        """Switch back to the original branch (keeping refactor branch)."""
        if self._original_branch:
            self.repo.heads[self._original_branch].checkout()
            logger.info("switched_to_original", branch=self._original_branch)

    def is_dirty(self) -> bool:
        """Check if the working tree has uncommitted changes."""
        return self.repo.is_dirty(untracked_files=True)

    def get_changed_files(self) -> list[str]:
        """Get list of files changed compared to original branch."""
        if self._original_branch:
            return [
                item.a_path
                for item in self.repo.index.diff(self._original_branch)
            ]
        return []
