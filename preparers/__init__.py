"""Framework-specific documentation preparers for Lore."""

from .base import FrameworkPreparer, PreparedDoc
from .registry import discover_all, run_all

__all__ = [
    "FrameworkPreparer",
    "PreparedDoc",
    "discover_all",
    "run_all",
]