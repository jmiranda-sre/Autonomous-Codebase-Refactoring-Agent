"""AST Analyzer — scans Python files, builds AST, identifies refactoring candidates."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

import structlog

from refactor_agent.config import RefactorConfig, ScanConfig

logger = structlog.get_logger(__name__)


@dataclass
class FunctionCandidate:
    """A function/method identified as a refactoring candidate."""

    name: str
    file_path: Path
    start_line: int
    end_line: int
    source: str
    params_count: int
    lines_count: int
    cyclomatic_complexity: int
    violations: list[str] = field(default_factory=list)
    parent_class: str | None = None
    docstring: str | None = None


@dataclass
class ClassCandidate:
    """A class identified as a refactoring candidate."""

    name: str
    file_path: Path
    start_line: int
    end_line: int
    source: str
    method_count: int
    lines_count: int
    violations: list[str] = field(default_factory=list)
    docstring: str | None = None
    methods: list[FunctionCandidate] = field(default_factory=list)


@dataclass
class FileAnalysis:
    """Analysis result for a single Python file."""

    file_path: Path
    function_candidates: list[FunctionCandidate] = field(default_factory=list)
    class_candidates: list[ClassCandidate] = field(default_factory=list)
    parse_error: str | None = None


class CyclomaticComplexityVisitor(ast.NodeVisitor):
    """Computes cyclomatic complexity by counting decision points."""

    DECISION_NODES = (
        ast.If, ast.For, ast.While, ast.ExceptHandler,
        ast.With, ast.Assert,
    )

    def __init__(self) -> None:
        self.complexity = 1  # base complexity

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, self.DECISION_NODES):
            self.complexity += 1
        # Boolean operators (and/or) each add 1
        if isinstance(node, ast.BoolOp):
            self.complexity += len(node.values) - 1
        # Comprehensions with multiple generators
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            self.complexity += len(node.generators) - 1
            for gen in node.generators:
                self.complexity += len(gen.ifs)
        super().visit(node)


def _compute_cyclomatic_complexity(node: ast.AST) -> int:
    """Compute cyclomatic complexity for an AST node."""
    visitor = CyclomaticComplexityVisitor()
    visitor.visit(node)
    return visitor.complexity


def _get_source_segment(source: str, node: ast.AST) -> str:
    """Extract source code for an AST node using line numbers."""
    lines = source.splitlines(keepends=True)
    start = node.body[0].lineno - 1 if hasattr(node, 'body') and node.body else node.lineno - 1
    end = node.end_lineno or node.lineno
    return "".join(lines[start:end])


def _should_exclude(path: Path, config: ScanConfig) -> bool:
    """Check if a file should be excluded based on config patterns."""
    name = path.name
    for pattern in config.exclude_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def scan_repository(
    target_dir: Path,
    scan_config: ScanConfig,
) -> Generator[Path, None, None]:
    """Walk directory tree and yield Python file paths matching config."""
    target_dir = target_dir.resolve()

    for root, dirs, files in os_walk_filtered(target_dir, scan_config.exclude_dirs):
        root_path = Path(root)
        for filename in sorted(files):
            if not any(fnmatch.fnmatch(filename, pat) for pat in scan_config.include_patterns):
                continue
            file_path = root_path / filename
            if _should_exclude(file_path, scan_config):
                logger.debug("exclude_pattern_match", file=str(file_path))
                continue
            yield file_path


def os_walk_filtered(root: Path, exclude_dirs: list[str]) -> Generator:
    """os.walk that prunes excluded directories."""
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith(".")]
        yield dirpath, dirnames, filenames


class ASTAnalyzer:
    """Analyzes Python files' AST to identify refactoring candidates."""

    def __init__(self, scan_config: ScanConfig, refactor_config: RefactorConfig) -> None:
        self.scan_config = scan_config
        self.refactor_config = refactor_config

    def analyze_file(self, file_path: Path) -> FileAnalysis:
        """Analyze a single Python file and identify candidates."""
        result = FileAnalysis(file_path=file_path)

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            result.parse_error = str(exc)
            logger.warning("parse_error", file=str(file_path), error=str(exc))
            return result
        except Exception as exc:
            result.parse_error = str(exc)
            logger.warning("read_error", file=str(file_path), error=str(exc))
            return result

        source_lines = source.splitlines(keepends=True)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                candidate = self._analyze_function(node, file_path, source_lines)
                if candidate and candidate.violations:
                    result.function_candidates.append(candidate)

            elif isinstance(node, ast.ClassDef):
                candidate = self._analyze_class(node, file_path, source_lines)
                if candidate and candidate.violations:
                    result.class_candidates.append(candidate)

        logger.info(
            "file_analyzed",
            file=str(file_path),
            functions=len(result.function_candidates),
            classes=len(result.class_candidates),
        )
        return result

    def _analyze_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: Path,
        source_lines: list[str],
    ) -> FunctionCandidate | None:
        """Evaluate a function/method against refactoring thresholds."""
        start_line = node.lineno
        end_line = node.end_lineno or node.lineno
        lines_count = end_line - start_line + 1

        # Extract source
        extracted = "".join(source_lines[start_line - 1:end_line])

        # Parameters count (excluding 'self' for methods)
        params = node.args
        param_count = len(params.args) + len(params.posonlyargs) + len(params.kwonlyargs)
        if params.vararg:
            param_count += 1
        if params.kwarg:
            param_count += 1
        has_self = params.args and params.args[0].arg == "self"
        effective_params = param_count - (1 if has_self else 0)

        # Cyclomatic complexity
        complexity = _compute_cyclomatic_complexity(node)

        # Docstring
        docstring = ast.get_docstring(node)

        # Parent class (for methods)
        parent_class = None
        # This is set externally by _analyze_class when iterating methods

        # Identify violations
        violations: list[str] = []
        rc = self.refactor_config

        if lines_count > rc.max_function_lines:
            violations.append(
                f"FUNCTION_TOO_LONG: {lines_count} lines (max {rc.max_function_lines})"
            )
        if effective_params > rc.max_function_params:
            violations.append(
                f"TOO_MANY_PARAMS: {effective_params} params (max {rc.max_function_params})"
            )
        if complexity > rc.max_cyclomatic_complexity:
            violations.append(
                f"HIGH_CYCLOMATIC: complexity={complexity} (max {rc.max_cyclomatic_complexity})"
            )

        # Check for SRP violation: function doing too many things
        # Heuristic: multiple assignment groups, nested ifs
        nested_depth = self._compute_nesting_depth(node)
        if nested_depth > 3:
            violations.append(f"DEEP_NESTING: depth={nested_depth} (max 3)")

        # Check for long parameter list with defaults (code smell)
        if len(params.defaults) > 3:
            violations.append("MANY_DEFAULTS: excessive default parameters")

        return FunctionCandidate(
            name=node.name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            source=extracted,
            params_count=effective_params,
            lines_count=lines_count,
            cyclomatic_complexity=complexity,
            violations=violations,
            parent_class=parent_class,
            docstring=docstring,
        )

    def _analyze_class(
        self,
        node: ast.ClassDef,
        file_path: Path,
        source_lines: list[str],
    ) -> ClassCandidate | None:
        """Evaluate a class against refactoring thresholds."""
        start_line = node.lineno
        end_line = node.end_lineno or node.lineno
        lines_count = end_line - start_line + 1

        extracted = "".join(source_lines[start_line - 1:end_line])

        # Count methods (excluding __init__, __repr__, etc. dunder methods)
        method_nodes = [
            n for n in node.body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        method_count = len(method_nodes)

        docstring = ast.get_docstring(node)

        violations: list[str] = []
        rc = self.refactor_config

        if method_count > rc.max_class_methods:
            violations.append(
                f"TOO_MANY_METHODS: {method_count} (max {rc.max_class_methods})"
            )
        if lines_count > rc.max_class_lines:
            violations.append(
                f"CLASS_TOO_LONG: {lines_count} lines (max {rc.max_class_lines})"
            )

        # SRP heuristic: check for method groups with different concerns
        method_names = [m.name for m in method_nodes]
        prefixes = set()
        for name in method_names:
            parts = name.split("_")
            if len(parts) > 1:
                prefixes.add(parts[0])
        if len(prefixes) >= 3:
            violations.append(
                f"SRP_VIOLATION: {len(prefixes)} distinct method prefixes — "
                f"possible multiple responsibilities"
            )

        # Analyze individual methods
        method_candidates: list[FunctionCandidate] = []
        for method_node in method_nodes:
            method_candidate = self._analyze_function(method_node, file_path, source_lines)
            if method_candidate:
                method_candidate.parent_class = node.name
                if method_candidate.violations:
                    method_candidates.append(method_candidate)

        return ClassCandidate(
            name=node.name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            source=extracted,
            method_count=method_count,
            lines_count=lines_count,
            violations=violations,
            docstring=docstring,
            methods=method_candidates,
        )

    @staticmethod
    def _compute_nesting_depth(node: ast.AST, current: int = 0) -> int:
        """Compute maximum nesting depth of control structures."""
        max_depth = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                child_depth = ASTAnalyzer._compute_nesting_depth(child, current + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = ASTAnalyzer._compute_nesting_depth(child, current)
                max_depth = max(max_depth, child_depth)
        return max_depth

    def analyze_repository(self, target_dir: Path) -> list[FileAnalysis]:
        """Analyze all Python files in the repository."""
        results: list[FileAnalysis] = []

        for file_path in scan_repository(target_dir, self.scan_config):
            logger.info("analyzing", file=str(file_path))
            analysis = self.analyze_file(file_path)
            results.append(analysis)

        total_functions = sum(len(r.function_candidates) for r in results)
        total_classes = sum(len(r.class_candidates) for r in results)
        logger.info(
            "repository_analyzed",
            total_files=len(results),
            total_function_candidates=total_functions,
            total_class_candidates=total_classes,
        )
        return results
