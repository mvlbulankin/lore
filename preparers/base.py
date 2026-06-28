from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PreparedDoc:
    relative_path: str
    content: str


@runtime_checkable
class FrameworkPreparer(Protocol):
    name: str
    source_dir: Path
    prepared_dir: Path

    def discover(self) -> list[Path]: ...

    def transform(self, src: Path) -> PreparedDoc | None: ...

    def cleanup(self) -> None: ...

    def run(self, execute: bool = False) -> None: ...