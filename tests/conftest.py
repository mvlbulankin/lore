"""Test configuration.

pytest pythonpath is set via [tool.pytest.ini_options] in pyproject.toml.
This file is kept for future fixtures.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
