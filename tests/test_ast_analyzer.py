"""Tests for the AST analyzer module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from refactor_agent.analyzers.ast_analyzer import (
    ASTAnalyzer,
    CyclomaticComplexityVisitor,
    _compute_cyclomatic_complexity,
    scan_repository,
    FileAnalysis,
)
from refactor_agent.config import ScanConfig, RefactorConfig


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample Python files."""
    # Simple clean file
    (tmp_path / "clean.py").write_text(textwrap.dedent("""\
        def hello(name: str) -> str:
            return f"Hello, {name}!"
    """), encoding="utf-8")

    # Legacy-style file with violations
    (tmp_path / "legacy.py").write_text(textwrap.dedent("""\
        def bloated_function(a, b, c, d, e, f, g, h):
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

    # File with syntax error
    (tmp_path / "broken.py").write_text("def foo(:\n    pass\n", encoding="utf-8")

    # File that should be excluded
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "vendor.py").write_text("import os\n", encoding="utf-8")

    # Test file (should be excluded by pattern)
    (tmp_path / "test_sample.py").write_text("def test_thing(): pass\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def analyzer() -> ASTAnalyzer:
    scan_config = ScanConfig()
    refactor_config = RefactorConfig(
        max_function_lines=10,
        max_function_params=5,
        max_cyclomatic_complexity=5,
        max_class_methods=5,
        max_class_lines=50,
    )
    return ASTAnalyzer(scan_config, refactor_config)


class TestCyclomaticComplexity:
    def test_simple_function(self):
        code = "def foo(): pass"
        tree = ast.parse(code)
        assert _compute_cyclomatic_complexity(tree) == 1

    def test_single_if(self):
        code = textwrap.dedent("""\
            def foo(x):
                if x:
                    return 1
                return 0
        """)
        tree = ast.parse(code)
        func = tree.body[0]
        assert _compute_cyclomatic_complexity(func) == 2

    def test_multiple_branches(self):
        code = textwrap.dedent("""\
            def foo(a, b):
                if a:
                    pass
                elif b:
                    pass
                else:
                    pass
                for i in range(10):
                    if i > 5:
                        break
        """)
        tree = ast.parse(code)
        func = tree.body[0]
        # if(1) + elif(1) + else(0) + for(1) + if(1) = base(1) + 4 = 5
        assert _compute_cyclomatic_complexity(func) == 5

    def test_bool_ops(self):
        code = textwrap.dedent("""\
            def foo(a, b, c):
                if a and b or c:
                    return True
        """)
        tree = ast.parse(code)
        func = tree.body[0]
        # base(1) + if(1) + and(1) + or(1) = 4
        assert _compute_cyclomatic_complexity(func) == 4


class TestScanRepository:
    def test_finds_python_files(self, sample_dir: Path):
        config = ScanConfig()
        files = list(scan_repository(sample_dir, config))
        filenames = [f.name for f in files]
        assert "clean.py" in filenames
        assert "legacy.py" in filenames

    def test_excludes_dirs(self, sample_dir: Path):
        config = ScanConfig()
        files = list(scan_repository(sample_dir, config))
        filenames = [f.name for f in files]
        assert "vendor.py" not in filenames  # inside venv/

    def test_excludes_patterns(self, sample_dir: Path):
        config = ScanConfig()
        files = list(scan_repository(sample_dir, config))
        filenames = [f.name for f in files]
        assert "test_sample.py" not in filenames


class TestASTAnalyzer:
    def test_clean_function_no_violations(self, analyzer: ASTAnalyzer, sample_dir: Path):
        result = analyzer.analyze_file(sample_dir / "clean.py")
        assert result.parse_error is None
        assert len(result.function_candidates) == 0  # clean function

    def test_bloated_function_detected(self, analyzer: ASTAnalyzer, sample_dir: Path):
        result = analyzer.analyze_file(sample_dir / "legacy.py")
        assert result.parse_error is None
        assert len(result.function_candidates) >= 1
        func = result.function_candidates[0]
        assert func.name == "bloated_function"
        assert func.params_count == 8
        assert func.lines_count > 10
        assert func.cyclomatic_complexity > 5
        assert any("TOO_MANY_PARAMS" in v for v in func.violations)
        assert any("FUNCTION_TOO_LONG" in v for v in func.violations)
        assert any("HIGH_CYCLOMATIC" in v for v in func.violations)

    def test_syntax_error_handled(self, analyzer: ASTAnalyzer, sample_dir: Path):
        result = analyzer.analyze_file(sample_dir / "broken.py")
        assert result.parse_error is not None

    def test_class_analysis(self, tmp_path: Path, analyzer: ASTAnalyzer):
        code = textwrap.dedent("""\
            class BigClass:
                def method1(self): pass
                def method2(self): pass
                def method3(self): pass
                def method4(self): pass
                def method5(self): pass
                def method6(self): pass
                def method7(self): pass
        """)
        (tmp_path / "bigclass.py").write_text(code, encoding="utf-8")
        result = analyzer.analyze_file(tmp_path / "bigclass.py")
        assert len(result.class_candidates) == 1
        cls = result.class_candidates[0]
        assert cls.method_count == 7
        assert any("TOO_MANY_METHODS" in v for v in cls.violations)

    def test_nesting_depth(self, analyzer: ASTAnalyzer):
        code = textwrap.dedent("""\
            def deep_nest(a, b, c, d):
                if a:
                    if b:
                        if c:
                            if d:
                                return 1
                return 0
        """)
        tree = ast.parse(code)
        func = tree.body[0]
        depth = analyzer._compute_nesting_depth(func)
        assert depth == 4

    def test_analyze_repository(self, analyzer: ASTAnalyzer, sample_dir: Path):
        results = analyzer.analyze_repository(sample_dir)
        assert isinstance(results, list)
        assert all(isinstance(r, FileAnalysis) for r in results)
