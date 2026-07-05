# Preparers

**Files:** `preparers/base.py`, `preparers/registry.py`, `preparers/cli.py`, `preparers/_atomic.py`

## FrameworkPreparer Protocol

```python
@runtime_checkable
class FrameworkPreparer(Protocol):
    name: str
    source_dir: Path
    prepared_dir: Path

    def discover(self) -> list[Path]: ...
    def transform(self, src: Path) -> PreparedDoc | None: ...
    def cleanup(self) -> None: ...
    def run(self, execute: bool = False) -> None: ...
```

Each framework implements this protocol in `preparers/{name}/prepare.py` as a `PREPARER` module-level instance.

## PreparedDoc

```python
@dataclass(frozen=True)
class PreparedDoc:
    relative_path: str   # path relative to prepared_dir
    content: str          # cleaned markdown content
```

## Registry

`discover_all(source_root, prepared_root)` auto-discovers preparers by:
1. Iterating `_PREPARER_PACKAGES` (`preparers.delta`, `preparers.spark`, `preparers.test`)
2. Importing each `{pkg}.prepare` module
3. Getting the `PREPARER` attribute
4. Setting `source_dir` and `prepared_dir` on the instance

## Atomic Publishing

`_atomic_publish()` in `_atomic.py` ensures consistency:
1. Build all output in a staging directory
2. Rename old `prepared_dir` to `_backup_{name}`
3. Rename staging to `prepared_dir`
4. Delete backup

This guarantees that `make ingest` always reads a consistent snapshot.

## Built-in Preparers

| Framework | Input Format | Transformations |
|-----------|-------------|-----------------|
| `spark` | Jekyll `.md` | HTML cleanup, notebook cell marker removal, redirect stub filtering, empty fence cleanup |
| `delta` | MDX + Python | MDX→MD conversion, Python→MD conversion |
| `test` | Plain `.md` | Trivial copy |

## CLI

```bash
python -m preparers.cli                          # dry-run
python -m preparers.cli --execute                 # all frameworks
python -m preparers.cli --framework spark --execute  # single framework
python -m preparers.cli --no-download             # skip network downloads
```

| Flag | Description |
|------|-------------|
| `--execute` | Apply changes (default: dry-run) |
| `--framework <name>` | Run only the named framework |
| `--no-download` | Skip network downloads (e.g. PySpark HTML pages) |
| `--source-root <path>` | Override source directory (default: `data/source`) |
| `--prepared-root <path>` | Override prepared directory (default: `data/prepared`) |

## Adding a New Framework

1. **Create preparer module** — add `preparers/{name}/prepare.py` with a module-level `PREPARER` instance
2. **Implement `FrameworkPreparer` protocol** — implement `name`, `source_dir`, `prepared_dir`, `discover()`, `transform()`, `cleanup()`, and `run()`
3. **Register the package** — add `preparers.{name}` to `_PREPARER_PACKAGES` in `preparers/registry.py`
4. **Place source files** — put raw documentation in `data/source/{name}/`
5. **Prepare and verify** — run `make prepare`, inspect `data/prepared/{name}/` for correct output
6. **Ingest** — run `make ingest` to index the new framework into Qdrant (dense + sparse)
