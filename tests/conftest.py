"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path for test imports
src = Path(__file__).parent.parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))
