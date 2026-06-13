"""LLM Client — interfaces with local Ollama/Qwen for code refactoring."""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from refactor_agent.config import LLMConfig
from refactor_agent.analyzers.ast_analyzer import FunctionCandidate, ClassCandidate

logger = structlog.get_logger(__name__)


@dataclass
class LLMResponse:
    """Parsed response from the LLM."""

    raw: str
    refactored_code: str | None
    is_valid_python: bool
    error: str | None = None


# ============================================================================
# Prompt Templates
# ============================================================================

FUNCTION_REFACTOR_PROMPT = """\
You are an expert Python software engineer specializing in Clean Code and SOLID principles.

## Task
Refactor the following Python {type} according to Clean Code and SOLID principles.

## Original Code
```python
{source}
```

## Identified Issues
{violations}

## Context
- File: `{file_path}`
- Lines: {start_line}-{end_line}
{docstring_context}
{class_context}

## Refactoring Guidelines
Apply ALL applicable principles:

### Clean Code
- **Single Responsibility**: Each function should do ONE thing well.
- **Small Functions**: Functions should be ≤ 20 lines. Extract helper functions.
- **Meaningful Names**: Rename obscure variables/functions to reveal intent.
- **No Side Effects**: Functions should not have hidden side effects.
- **DRY**: Eliminate duplicated logic.

### SOLID Principles
- **S (Single Responsibility)**: A class/function should have only one reason to change.
- **O (Open/Closed)**: Design for extension, not modification. Use strategy/template method.
- **L (Liskov Substitution)**: Subtypes must be substitutable for base types.
- **I (Interface Segregation)**: Prefer many specific interfaces over one fat interface.
- **D (Dependency Inversion)**: Depend on abstractions, not concretions. Inject dependencies.

### Additional Rules
- Preserve the same public API (function name, parameters, return type) unless a rename significantly improves clarity.
- If you extract new helper functions/classes, include them in the output.
- Add type hints if missing.
- Add docstrings if missing.
- Remove dead code, commented-out code, and unused imports.
- Maintain or improve test compatibility.

## Output Format
Return ONLY the refactored Python code. No explanations outside code.
Use inline comments with `# REFACTOR:` prefix to annotate key changes.
Example: `# REFACTOR: Extracted validation logic into separate function`

```python
# Your refactored code here
```
"""

CLASS_REFACTOR_PROMPT = """\
You are an expert Python software engineer specializing in Clean Code and SOLID principles.

## Task
Refactor the following Python class according to Clean Code and SOLID principles.
The class has been identified as having potential design issues.

## Original Code
```python
{source}
```

## Identified Issues
{violations}

## Context
- File: `{file_path}`
- Lines: {start_line}-{end_line}
{docstring_context}

## Refactoring Guidelines
Apply ALL applicable principles:

### Class Design
- **Single Responsibility**: Split into focused classes if the class handles multiple concerns.
- **Open/Closed**: Use composition and strategy pattern over modifying existing code.
- **Dependency Inversion**: Accept dependencies through constructor injection.
- **Encapsulation**: Make attributes private (prefix `_`) and expose via properties.
- **Composition over Inheritance**: Prefer composing behaviors over deep inheritance.

### Method Design
- Each method should be ≤ 20 lines.
- Extract complex logic into well-named private methods.
- Reduce parameter counts by introducing parameter objects or builders.

### Output Format
- If splitting into multiple classes, include ALL classes in the output.
- If extracting a base class/protocol, include it.
- Preserve the public API where possible. If changes are breaking, add a deprecation path.
- Add type hints and docstrings.
- Use `# REFACTOR:` comments to annotate key changes.

Return ONLY the refactored Python code wrapped in a code block:

```python
# Your refactored code here
```
"""


def _format_violations(violations: list[str]) -> str:
    return "\n".join(f"- {v}" for v in violations)


class LLMClient:
    """Client for interacting with local LLM services (Ollama/Qwen)."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = httpx.Client(timeout=config.timeout)

    def _build_ollama_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

    def _build_openai_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": "You are an expert Python refactoring assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    def call_llm(self, prompt: str) -> str:
        """Send prompt to LLM and return raw text response."""
        provider = self.config.provider.lower()

        if provider == "ollama":
            url = f"{self.config.endpoint.rstrip('/')}/api/generate"
            payload = self._build_ollama_payload(prompt)
        elif provider in ("qwen", "openai", "vllm"):
            url = f"{self.config.endpoint.rstrip('/')}/v1/chat/completions"
            payload = self._build_openai_payload(prompt)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        logger.info("llm_request", provider=provider, model=self.config.model, url=url)

        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException:
            logger.error("llm_timeout", provider=provider, timeout=self.config.timeout)
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "llm_http_error",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise

        data = response.json()

        if provider == "ollama":
            return data.get("response", "")
        else:
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    @staticmethod
    def _extract_code_block(text: str) -> str | None:
        """Extract Python code from markdown code block."""
        # Match ```python ... ``` or ``` ... ```
        pattern = r"```(?:python)?\s*\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: if no code fences, try to parse entire response as code
        # Check if the whole thing looks like Python
        stripped = text.strip()
        if stripped and not stripped.startswith(("#", "Here", "I ", "The ", "Below")):
            return stripped
        return None

    @staticmethod
    def _validate_python(code: str) -> bool:
        """Check if the code is syntactically valid Python."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def refactor_function(self, candidate: FunctionCandidate) -> LLMResponse:
        """Send a function candidate to the LLM for refactoring."""
        docstring_ctx = ""
        if candidate.docstring:
            docstring_ctx = f"- Docstring: {candidate.docstring}"

        class_ctx = ""
        if candidate.parent_class:
            class_ctx = f"- Method of class: `{candidate.parent_class}`"

        prompt = FUNCTION_REFACTOR_PROMPT.format(
            type="method" if candidate.parent_class else "function",
            source=candidate.source,
            violations=_format_violations(candidate.violations),
            file_path=candidate.file_path,
            start_line=candidate.start_line,
            end_line=candidate.end_line,
            docstring_context=docstring_ctx,
            class_context=class_ctx,
        )

        logger.info(
            "refactor_function_request",
            function=candidate.name,
            file=str(candidate.file_path),
        )

        raw_response = self.call_llm(prompt)
        refactored = self._extract_code_block(raw_response)

        is_valid = False
        error = None
        if refactored:
            is_valid = self._validate_python(refactored)
            if not is_valid:
                error = "LLM output failed Python syntax validation"

        return LLMResponse(
            raw=raw_response,
            refactored_code=refactored,
            is_valid_python=is_valid,
            error=error,
        )

    def refactor_class(self, candidate: ClassCandidate) -> LLMResponse:
        """Send a class candidate to the LLM for refactoring."""
        docstring_ctx = ""
        if candidate.docstring:
            docstring_ctx = f"- Docstring: {candidate.docstring}"

        prompt = CLASS_REFACTOR_PROMPT.format(
            source=candidate.source,
            violations=_format_violations(candidate.violations),
            file_path=candidate.file_path,
            start_line=candidate.start_line,
            end_line=candidate.end_line,
            docstring_context=docstring_ctx,
        )

        logger.info(
            "refactor_class_request",
            class_name=candidate.name,
            file=str(candidate.file_path),
        )

        raw_response = self.call_llm(prompt)
        refactored = self._extract_code_block(raw_response)

        is_valid = False
        error = None
        if refactored:
            is_valid = self._validate_python(refactored)
            if not is_valid:
                error = "LLM output failed Python syntax validation"

        return LLMResponse(
            raw=raw_response,
            refactored_code=refactored,
            is_valid_python=is_valid,
            error=error,
        )

    def close(self) -> None:
        self._client.close()
