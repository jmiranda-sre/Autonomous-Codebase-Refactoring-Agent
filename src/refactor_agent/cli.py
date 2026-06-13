#!/usr/bin/env python3
"""CLI — command-line interface for the Autonomous Codebase Refactoring Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from refactor_agent import __version__
from refactor_agent.config import load_config, AgentConfig
from refactor_agent.analyzers.ast_analyzer import ASTAnalyzer
from refactor_agent.orchestrator import RefactorOrchestrator
from refactor_agent.reports.generator import AgentReport

console = Console()
logger = structlog.get_logger(__name__)


def _configure_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = "DEBUG" if verbose else "INFO"
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def cmd_scan(args: argparse.Namespace) -> None:
    """Scan and analyze a repository without applying changes."""
    config = load_config(args.config)
    target = Path(args.target).resolve()

    if not target.exists():
        console.print(f"[red]Error:[/red] Directory not found: {target}")
        sys.exit(1)

    console.print(Panel(f"Scanning: {target}", title="Refactor Agent — Scan Mode"))

    analyzer = ASTAnalyzer(config.scan, config.refactor)
    analyses = analyzer.analyze_repository(target)

    # Summary table
    summary = Table(title="Scan Results")
    summary.add_column("File", style="cyan")
    summary.add_column("Functions", justify="right")
    summary.add_column("Classes", justify="right")
    summary.add_column("Errors", justify="right")

    total_funcs = 0
    total_classes = 0

    for analysis in analyses:
        func_count = len(analysis.function_candidates)
        class_count = len(analysis.class_candidates)
        total_funcs += func_count
        total_classes += class_count
        error = analysis.parse_error or ""

        summary.add_row(
            str(analysis.file_path),
            str(func_count),
            str(class_count),
            error[:50] if error else "—",
        )

    console.print(summary)

    # Print candidate details
    for analysis in analyses:
        for func in analysis.function_candidates:
            console.print(f"\n[yellow]Function:[/yellow] {func.name} ({func.file_path}:{func.start_line})")
            console.print(f"  Lines: {func.lines_count} | Params: {func.params_count} | Complexity: {func.cyclomatic_complexity}")
            for v in func.violations:
                console.print(f"  [red]✗[/red] {v}")

        for cls in analysis.class_candidates:
            console.print(f"\n[yellow]Class:[/yellow] {cls.name} ({cls.file_path}:{cls.start_line})")
            console.print(f"  Lines: {cls.lines_count} | Methods: {cls.method_count}")
            for v in cls.violations:
                console.print(f"  [red]✗[/red] {v}")

    console.print(f"\n[bold]Total:[/bold] {len(analyses)} files, {total_funcs} functions, {total_classes} classes")


def cmd_refactor(args: argparse.Namespace) -> None:
    """Run the full autonomous refactoring workflow."""
    config = load_config(args.config)
    target = Path(args.target).resolve()

    if not target.exists():
        console.print(f"[red]Error:[/red] Directory not found: {target}")
        sys.exit(1)

    # Allow CLI overrides
    if args.model:
        config.llm.model = args.model
    if args.endpoint:
        config.llm.endpoint = args.endpoint
    if args.provider:
        config.llm.provider = args.provider
    if args.dry_run:
        config.git.auto_branch = False
        config.git.commit_on_pass = False

    console.print(Panel(
        f"Target: {target}\n"
        f"Model: {config.llm.model}\n"
        f"Provider: {config.llm.provider}\n"
        f"Dry Run: {args.dry_run}",
        title="Refactor Agent — Autonomous Mode",
    ))

    orchestrator = RefactorOrchestrator(config, target)
    report = orchestrator.run()

    _print_report(report)


def cmd_config(args: argparse.Namespace) -> None:
    """Show current configuration."""
    config = load_config(args.config)
    _print_config(config)


def _print_config(config: AgentConfig) -> None:
    """Pretty-print the loaded configuration."""
    table = Table(title="Current Configuration")
    table.add_column("Section", style="cyan")
    table.add_column("Key", style="green")
    table.add_column("Value")

    for section_name, section in [
        ("LLM", config.llm),
        ("Scan", config.scan),
        ("Refactor", config.refactor),
        ("Git", config.git),
        ("Test", config.test),
        ("Report", config.report),
    ]:
        for key, value in section.__dict__.items():
            table.add_row(section_name, key, str(value))

    console.print(table)


def _print_report(report: AgentReport) -> None:
    """Print a summary of the refactoring report."""
    console.print(Panel(
        f"Files Scanned: {report.files_scanned}\n"
        f"Candidates Found: {report.functions_identified + report.classes_identified}\n"
        f"Refactorings Applied: {report.total_refactorings_applied}\n"
        f"Committed: {report.total_refactorings_committed}\n"
        f"Rolled Back: {report.total_refactorings_rolled_back}",
        title="Refactoring Report",
    ))

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for err in report.errors:
            console.print(f"  [red]✗[/red] {err}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="refactor-agent",
        description="Autonomous Codebase Refactoring Agent — AST + LLM + Git",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", type=str, default=None, help="Path to config TOML file")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Scan and analyze without modifying")
    scan_parser.add_argument("target", type=str, help="Target directory to scan")

    # refactor subcommand
    refactor_parser = subparsers.add_parser("refactor", help="Run autonomous refactoring")
    refactor_parser.add_argument("target", type=str, help="Target directory to refactor")
    refactor_parser.add_argument("--model", type=str, help="Override LLM model name")
    refactor_parser.add_argument("--endpoint", type=str, help="Override LLM endpoint URL")
    refactor_parser.add_argument("--provider", type=str, help="Override LLM provider (ollama/qwen)")
    refactor_parser.add_argument("--dry-run", action="store_true", help="Preview changes without committing")

    # config subcommand
    config_parser = subparsers.add_parser("config", help="Show current configuration")

    return parser


def main() -> None:
    """Entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    _configure_logging(verbose=args.verbose)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "refactor":
        cmd_refactor(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
