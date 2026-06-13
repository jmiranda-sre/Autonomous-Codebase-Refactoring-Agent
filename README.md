# Autonomous Codebase Refactoring Agent

A CLI tool that scans Python repositories, analyzes the AST to detect Clean Code and SOLID violations, and uses local LLMs (Ollama/Qwen) to autonomously refactor code — with Git branch safety and test-suite validation.

## How It Works

```
┌───────────────┐     ┌───────────────┐     ┌─────────────┐     ┌───────────────┐
│  1. SCAN      │───▶│  2. BRANCH    │───▶│ 3. REFACTOR │───▶│ 4. VALIDATE   │
│  AST Analysis │     │  Git Safety   │     │ LLM + Apply │     │ Tests + Commit│
└───────────────┘     └───────────────┘     └─────────────┘     └───────────────┘
  Walk repo          Auto-create         Prompt LLM          Run pytest
  Parse AST          refactor/           Extract code        Pass → commit
  Detect smells      branch              Validate syntax    Fail → rollback
```

### Phase 1 — Scan & Analyze

Walks the target directory, parses each `.py` file's AST, and identifies refactoring candidates based on configurable thresholds:

| Violation | Detection Method |
|-----------|-----------------|
| Function too long | Line count > `max_function_lines` |
| Too many parameters | Param count > `max_function_params` |
| High cyclomatic complexity | Decision nodes + boolean ops > `max_cyclomatic_complexity` |
| Deep nesting | Control flow depth > 3 |
| Class too large | Method count > `max_class_methods` or lines > `max_class_lines` |
| SRP violation | Distinct method prefixes ≥ 3 in same class |

### Phase 2 — Git Safety Branch

Automatically creates a `refactor/agent-<timestamp>` branch before any changes. Refuses to run if the working tree has uncommitted changes.

### Phase 3 — LLM Refactoring

For each candidate, builds a detailed prompt including:

- The original source code
- Identified violations
- Context (file path, line range, docstring, parent class)
- Full SOLID principles + Clean Code guidelines
- Output format instructions with `# REFACTOR:` annotations

The LLM response is parsed, extracted from code fences, and validated for Python syntax before application.

### Phase 4 — Test Validation & Conditional Commit

Runs the project's test suite after all refactoring is applied:

- **All tests pass** → changes are committed with a conventional commit message, and the agent switches back to the original branch
- **Any test fails** → all changes are rolled back, and the refactor branch is deleted or preserved for manual inspection

## Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install the agent
pip install -e .

# With dev dependencies (for running tests)
pip install -e ".[dev]"
```

## Quick Start

```bash
# Scan a repository — no changes, just analysis
refactor-agent scan ./my-project

# Run autonomous refactoring
refactor-agent refactor ./my-project

# Dry run (no branch, no commit)
refactor-agent refactor ./my-project --dry-run

# Override LLM settings
refactor-agent refactor ./my-project --model qwen2.5-coder:14b --endpoint http://gpu-server:11434

# View current configuration
refactor-agent config
```

## Configuration

Create an `agent_config.toml` in the project root, or use the default at `config/agent_config.toml`:

```toml
[llm]
endpoint = "http://localhost:11434"
model = "qwen2.5-coder:7b"
provider = "ollama"          # "ollama" | "qwen" | "openai" | "vllm"
temperature = 0.2
max_tokens = 4096
timeout = 120

[scan]
include_dirs = ["."]
exclude_dirs = ["venv", ".venv", "node_modules", ".git", "__pycache__"]
include_patterns = ["*.py"]
exclude_patterns = ["test_*.py", "conftest.py", "__init__.py"]

[refactor]
max_function_lines = 50
max_function_params = 5
max_cyclomatic_complexity = 10
max_class_methods = 15
max_class_lines = 300

[git]
branch_prefix = "refactor/agent"
auto_branch = true
commit_on_pass = true
discard_on_fail = true       # false = keep branch for manual inspection

[test]
command = "pytest"
args = ["-x", "--tb=short"]
timeout = 300

[report]
format = "json"              # "json" | "md" | "txt"
output_dir = "reports"
save_prompts = true
```

Environment variable overrides are also supported:

| Variable | Overrides |
|----------|-----------|
| `REFAGENT_LLM_ENDPOINT` | `llm.endpoint` |
| `REFAGENT_LLM_MODEL` | `llm.model` |
| `REFAGENT_LLM_PROVIDER` | `llm.provider` |
| `REFAGENT_TEST_COMMAND` | `test.command` |

## Project Structure

```
src/refactor_agent/
├── cli.py                  # CLI entry point (argparse + Rich)
├── config.py               # Typed config loader (TOML + env)
├── orchestrator.py          # 4-phase workflow engine
├── analyzers/
│   └── ast_analyzer.py      # AST scanning & violation detection
├── llm/
│   └── client.py            # Ollama/OpenAI client + prompt templates
├── git_utils/
│   └── workflow.py          # Branch, apply, commit, rollback
├── runners/
│   └── test_runner.py       # Subprocess test execution
└── reports/
    └── generator.py         # JSON/Markdown/Text reports
```

## Running Tests

```bash
# Full suite (59 tests)
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=refactor_agent --cov-report=term-missing
```

## Requirements

- Python 3.9+
- [Ollama](https://ollama.ai) or compatible local LLM server running
- Git repository for the target project

## Example Output

```
$ refactor-agent scan ./legacy-project

╭──────────────────────────────────────────────╮
│        Refactor Agent — Scan Mode             │
│ Scanning: /projects/legacy-project            │
╰───────────────────────────────────────────────╯

          Scan Results
┌──────────────────┬───────────┬─────────┬─────────┐
│ File             │ Functions │ Classes │ Errors  │
├──────────────────┼───────────┼─────────┼─────────┤
│ src/manager.py   │ 3         │ 1       │ —       │
│ src/utils.py     │ 2         │ 0       │ —       │
└──────────────────┴───────────┴─────────┴─────────┘

Function: process_order (src/manager.py:42)
  Lines: 87 | Params: 12 | Complexity: 15
  ✗ FUNCTION_TOO_LONG: 87 lines (max 50)
  ✗ TOO_MANY_PARAMS: 12 params (max 5)
  ✗ HIGH_CYCLOMATIC: complexity=15 (max 10)

Class: UserOrderManager (src/manager.py:1)
  Lines: 215 | Methods: 8
  ✗ CLASS_TOO_LONG: 215 lines (max 300)
  ✗ SRP_VIOLATION: 4 distinct method prefixes — possible multiple responsibilities

Total: 3 files, 5 functions, 1 class
```

## License

MIT
