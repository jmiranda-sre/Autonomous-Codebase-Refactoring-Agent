"""Tests for the configuration module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from refactor_agent.config import (
    AgentConfig,
    LLMConfig,
    ScanConfig,
    RefactorConfig,
    GitConfig,
    AgentTestConfig,
    ReportConfig,
    load_config,
)


class TestDefaultConfig:
    def test_default_config_raises_for_explicit_nonexistent(self):
        """When an explicit nonexistent path is given, it raises."""
        with pytest.raises(FileNotFoundError):
            load_config(path="/nonexistent.toml")

    def test_default_config_none_path(self, tmp_path: Path):
        # Run from tmp_path where no config file exists
        original = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            config = load_config()  # No path, no candidates found -> defaults
            assert isinstance(config, AgentConfig)
            assert config.llm.model == "qwen2.5-coder:7b"
            assert config.refactor.max_function_lines == 50
        finally:
            os.chdir(original)


class TestLoadConfig:
    def test_load_from_toml(self, tmp_path: Path):
        config_file = tmp_path / "agent_config.toml"
        config_file.write_text("""\
[llm]
endpoint = "http://custom:1234"
model = "custom-model"

[refactor]
max_function_lines = 25
""")
        config = load_config(config_file)
        assert config.llm.endpoint == "http://custom:1234"
        assert config.llm.model == "custom-model"
        assert config.refactor.max_function_lines == 25
        # Other values should be defaults
        assert config.refactor.max_function_params == 5

    def test_env_override(self, tmp_path: Path):
        os.environ["REFAGENT_LLM_MODEL"] = "env-model"
        try:
            config = load_config()
            assert config.llm.model == "env-model"
        finally:
            del os.environ["REFAGENT_LLM_MODEL"]

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.toml")


class TestConfigDataclasses:
    def test_llm_config_defaults(self):
        cfg = LLMConfig()
        assert cfg.provider == "ollama"
        assert cfg.temperature == 0.2

    def test_scan_config_defaults(self):
        cfg = ScanConfig()
        assert "venv" in cfg.exclude_dirs
        assert "*.py" in cfg.include_patterns

    def test_git_config_defaults(self):
        cfg = GitConfig()
        assert cfg.auto_branch is True
        assert cfg.discard_on_fail is True
