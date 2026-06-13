"""Configuration loader — reads agent_config.toml and provides typed access."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml


@dataclass
class LLMConfig:
    endpoint: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    provider: str = "ollama"
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: int = 120


@dataclass
class ScanConfig:
    include_dirs: list[str] = field(default_factory=lambda: ["."])
    exclude_dirs: list[str] = field(default_factory=lambda: [
        "venv", ".venv", "node_modules", ".git", "__pycache__",
        ".mypy_cache", ".pytest_cache", "dist", "build",
    ])
    include_patterns: list[str] = field(default_factory=lambda: ["*.py"])
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "test_*.py", "_test.py", "conftest.py", "setup.py", "__init__.py",
    ])


@dataclass
class RefactorConfig:
    max_function_lines: int = 50
    max_function_params: int = 5
    max_cyclomatic_complexity: int = 10
    max_class_methods: int = 15
    max_class_lines: int = 300


@dataclass
class GitConfig:
    branch_prefix: str = "refactor/agent"
    auto_branch: bool = True
    commit_on_pass: bool = True
    discard_on_fail: bool = True


@dataclass
class AgentTestConfig:
    command: str = "pytest"
    args: list[str] = field(default_factory=lambda: ["-x", "--tb=short"])
    timeout: int = 300


@dataclass
class ReportConfig:
    format: str = "json"
    output_dir: str = "reports"
    save_prompts: bool = True


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    refactor: RefactorConfig = field(default_factory=RefactorConfig)
    git: GitConfig = field(default_factory=GitConfig)
    test: AgentTestConfig = field(default_factory=AgentTestConfig)
    report: ReportConfig = field(default_factory=ReportConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Load config from TOML file, falling back to defaults."""
    defaults: dict[str, Any] = {
        "llm": LLMConfig().__dict__,
        "scan": ScanConfig().__dict__,
        "refactor": RefactorConfig().__dict__,
        "git": GitConfig().__dict__,
        "test": AgentTestConfig().__dict__,
        "report": ReportConfig().__dict__,
    }

    if path is None:
        candidates = [
            Path("agent_config.toml"),
            Path("config/agent_config.toml"),
            Path(".refactor-agent.toml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    if path is not None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        raw = toml.load(path)
        merged = _deep_merge(defaults, raw)
    else:
        merged = defaults

    # Environment variable overrides
    env_keys = {
        "REFAGENT_LLM_ENDPOINT": ("llm", "endpoint"),
        "REFAGENT_LLM_MODEL": ("llm", "model"),
        "REFAGENT_LLM_PROVIDER": ("llm", "provider"),
        "REFAGENT_TEST_COMMAND": ("test", "command"),
    }
    for env_key, (section, field_name) in env_keys.items():
        val = os.environ.get(env_key)
        if val:
            merged.setdefault(section, {})[field_name] = val

    return AgentConfig(
        llm=LLMConfig(**merged.get("llm", {})),
        scan=ScanConfig(**merged.get("scan", {})),
        refactor=RefactorConfig(**merged.get("refactor", {})),
        git=GitConfig(**merged.get("git", {})),
        test=AgentTestConfig(**merged.get("test", {})),
        report=ReportConfig(**merged.get("report", {})),
    )
