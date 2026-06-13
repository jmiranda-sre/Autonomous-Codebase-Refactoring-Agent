"""Tests for the CLI module."""

from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock

import pytest

from refactor_agent.cli import build_parser, main


class TestCLIParser:
    def test_version_flag(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_scan_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["scan", "/tmp/test-repo"])
        assert args.command == "scan"
        assert args.target == "/tmp/test-repo"

    def test_refactor_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["refactor", "/tmp/test-repo"])
        assert args.command == "refactor"
        assert args.target == "/tmp/test-repo"
        assert args.dry_run is False
        assert args.model is None

    def test_refactor_with_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "refactor", "/tmp/repo",
            "--model", "test-model",
            "--endpoint", "http://custom:1234",
            "--provider", "qwen",
            "--dry-run",
        ])
        assert args.model == "test-model"
        assert args.endpoint == "http://custom:1234"
        assert args.provider == "qwen"
        assert args.dry_run is True

    def test_config_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["config"])
        assert args.command == "config"

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-v", "scan", "/tmp/repo"])
        assert args.verbose is True
