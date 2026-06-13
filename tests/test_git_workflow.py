"""Tests for the Git workflow module."""

from __future__ import annotations

import textwrap
from pathlib import Path

import git
import pytest

from refactor_agent.config import GitConfig
from refactor_agent.git_utils.workflow import GitWorkflow, GitWorkflowError


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary Git repository with an initial commit."""
    repo = git.Repo.init(str(tmp_path))

    (tmp_path / "main.py").write_text(textwrap.dedent("""\
        def hello():
            print("hello")
    """), encoding="utf-8")

    repo.index.add(["main.py"])
    repo.index.commit("Initial commit")
    return tmp_path


@pytest.fixture
def git_config() -> GitConfig:
    return GitConfig(
        branch_prefix="refactor/test",
        auto_branch=True,
        commit_on_pass=True,
        discard_on_fail=True,
    )


class TestGitWorkflow:
    def test_create_refactor_branch(self, git_repo: Path, git_config: GitConfig):
        wf = GitWorkflow(git_repo, git_config)
        branch_name = wf.create_refactor_branch()

        assert branch_name.startswith("refactor/test-")
        assert wf.current_branch == branch_name
        assert wf._original_branch is not None

    def test_apply_refactoring(self, git_repo: Path, git_config: GitConfig):
        wf = GitWorkflow(git_repo, git_config)
        wf.create_refactor_branch()

        new_code = 'def hello():\n    return "hello"'
        wf.apply_refactoring(git_repo / "main.py", 1, 2, new_code)

        content = (git_repo / "main.py").read_text()
        assert 'return "hello"' in content

    def test_stage_and_commit(self, git_repo: Path, git_config: GitConfig):
        wf = GitWorkflow(git_repo, git_config)
        wf.create_refactor_branch()

        new_code = 'def hello():\n    return "hello"'
        wf.apply_refactoring(git_repo / "main.py", 1, 2, new_code)
        wf.stage_and_commit(git_repo / "main.py", "refactor: improve hello")

        repo = git.Repo(str(git_repo))
        assert not repo.is_dirty()

    def test_rollback_discards_changes(self, git_repo: Path, git_config: GitConfig):
        wf = GitWorkflow(git_repo, git_config)
        wf.create_refactor_branch()

        # Modify a file
        new_code = 'def hello():\n    return "hello"'
        wf.apply_refactoring(git_repo / "main.py", 1, 2, new_code)

        # Rollback
        wf.rollback()

        # Original content should be restored
        content = (git_repo / "main.py").read_text()
        assert 'print("hello")' in content

    def test_dirty_tree_raises(self, tmp_path: Path, git_config: GitConfig):
        repo = git.Repo.init(str(tmp_path))
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        repo.index.add(["app.py"])
        repo.index.commit("init")

        # Create uncommitted change
        (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")

        wf = GitWorkflow(tmp_path, git_config)
        with pytest.raises(GitWorkflowError, match="uncommitted changes"):
            wf.create_refactor_branch()

    def test_non_repo_raises(self, tmp_path: Path, git_config: GitConfig):
        wf = GitWorkflow(tmp_path, git_config)
        with pytest.raises(GitWorkflowError):
            _ = wf.repo

    def test_branch_kept_when_discard_false(self, git_repo: Path):
        config = GitConfig(
            branch_prefix="refactor/test",
            auto_branch=True,
            commit_on_pass=True,
            discard_on_fail=False,
        )
        wf = GitWorkflow(git_repo, config)
        branch_name = wf.create_refactor_branch()

        wf.rollback()

        repo = git.Repo(str(git_repo))
        branch_names = [h.name for h in repo.heads]
        assert branch_name in branch_names

    def test_auto_branch_disabled(self, git_repo: Path):
        config = GitConfig(branch_prefix="refactor/test", auto_branch=False)
        wf = GitWorkflow(git_repo, config)

        branch_name = wf.create_refactor_branch()
        # Should stay on current branch when auto_branch is False
        assert branch_name == wf.current_branch
