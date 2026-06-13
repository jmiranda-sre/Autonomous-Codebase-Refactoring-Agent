"""Tests for the LLM client module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from refactor_agent.config import LLMConfig
from refactor_agent.llm.client import LLMClient, LLMResponse
from refactor_agent.analyzers.ast_analyzer import FunctionCandidate, ClassCandidate


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        endpoint="http://localhost:11434",
        model="qwen2.5-coder:7b",
        provider="ollama",
        temperature=0.2,
        max_tokens=4096,
        timeout=30,
    )


@pytest.fixture
def client(llm_config: LLMConfig) -> LLMClient:
    return LLMClient(llm_config)


@pytest.fixture
def sample_function() -> FunctionCandidate:
    return FunctionCandidate(
        name="bloated_func",
        file_path=Path("src/module.py"),
        start_line=1,
        end_line=30,
        source=textwrap.dedent("""\
            def bloated_func(a, b, c, d, e, f, g, h):
                x = 1
                if a:
                    if b:
                        for i in range(100):
                            if d:
                                x += i
                return x
        """),
        params_count=8,
        lines_count=30,
        cyclomatic_complexity=8,
        violations=[
            "FUNCTION_TOO_LONG: 30 lines (max 10)",
            "TOO_MANY_PARAMS: 8 params (max 5)",
            "HIGH_CYCLOMATIC: complexity=8 (max 5)",
        ],
        parent_class=None,
        docstring=None,
    )


@pytest.fixture
def sample_class() -> ClassCandidate:
    return ClassCandidate(
        name="UserOrderManager",
        file_path=Path("src/manager.py"),
        start_line=1,
        end_line=200,
        source="class UserOrderManager: ...",
        method_count=12,
        lines_count=200,
        violations=["TOO_MANY_METHODS: 12 (max 15)", "CLASS_TOO_LONG: 200 lines (max 300)"],
        docstring="A big class",
    )


class TestCodeExtraction:
    def test_extract_python_code_block(self, client: LLMClient):
        response = """Here is the refactored code:

```python
def hello():
    return "world"
```

Hope this helps!"""
        result = client._extract_code_block(response)
        assert result is not None
        assert 'def hello():' in result

    def test_extract_code_block_no_language(self, client: LLMClient):
        response = """```
def foo():
    pass
```"""
        result = client._extract_code_block(response)
        assert result is not None
        assert "def foo" in result

    def test_extract_no_code_block(self, client: LLMClient):
        response = "Here is some plain text without code blocks."
        result = client._extract_code_block(response)
        # Should return None or the text itself
        # Current logic returns None since text starts with "Here"
        assert result is None


class TestPythonValidation:
    def test_valid_python(self, client: LLMClient):
        assert client._validate_python("def foo(): pass") is True

    def test_invalid_python(self, client: LLMClient):
        assert client._validate_python("def foo(: pass") is False

    def test_empty_string(self, client: LLMClient):
        assert client._validate_python("") is True  # Empty is technically valid


class TestPromptBuilding:
    @patch.object(LLMClient, "call_llm")
    def test_refactor_function_builds_prompt(self, mock_llm, client: LLMClient, sample_function: FunctionCandidate):
        mock_llm.return_value = '```python\ndef bloated_func(a, b): pass\n```'

        response = client.refactor_function(sample_function)

        assert mock_llm.called
        prompt = mock_llm.call_args[0][0]

        # Verify prompt contains key elements
        assert "bloated_func" in prompt
        assert "FUNCTION_TOO_LONG" in prompt
        assert "TOO_MANY_PARAMS" in prompt
        assert "SOLID" in prompt
        assert "Clean Code" in prompt
        assert "Single Responsibility" in prompt

    @patch.object(LLMClient, "call_llm")
    def test_refactor_class_builds_prompt(self, mock_llm, client: LLMClient, sample_class: ClassCandidate):
        mock_llm.return_value = '```python\nclass UserOrderManager: pass\n```'

        response = client.refactor_class(sample_class)

        assert mock_llm.called
        prompt = mock_llm.call_args[0][0]
        assert "UserOrderManager" in prompt
        assert "TOO_MANY_METHODS" in prompt
        assert "Composition over Inheritance" in prompt


class TestLLMResponse:
    @patch.object(LLMClient, "call_llm")
    def test_successful_refactor(self, mock_llm, client: LLMClient, sample_function: FunctionCandidate):
        mock_llm.return_value = '```python\ndef bloated_func(a: int, b: int) -> int:\n    return a + b\n```'

        response = client.refactor_function(sample_function)

        assert response.is_valid_python is True
        assert response.refactored_code is not None
        assert response.error is None

    @patch.object(LLMClient, "call_llm")
    def test_invalid_syntax_refactor(self, mock_llm, client: LLMClient, sample_function: FunctionCandidate):
        mock_llm.return_value = '```python\ndef bloated_func(:\n    pass\n```'

        response = client.refactor_function(sample_function)

        assert response.is_valid_python is False
        assert response.error is not None


class TestOllamaPayload:
    def test_ollama_payload_structure(self, client: LLMClient):
        payload = client._build_ollama_payload("test prompt")
        assert payload["model"] == "qwen2.5-coder:7b"
        assert payload["prompt"] == "test prompt"
        assert payload["stream"] is False
        assert "options" in payload


class TestOpenAIPayload:
    def test_openai_payload_structure(self, llm_config: LLMConfig):
        llm_config.provider = "qwen"
        client = LLMClient(llm_config)
        payload = client._build_openai_payload("test prompt")
        assert payload["model"] == "qwen2.5-coder:7b"
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"
