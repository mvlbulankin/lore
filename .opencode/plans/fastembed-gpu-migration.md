# Plan: Migration to FastEmbed GPU (CUDA)

## Context

`make ingest` saturates the host CPU to 100%, making the workstation unusable
during indexing. Embeddings are computed via `fastembed` (ONNX runtime) on
CPU inside the Lore Docker container, while an NVIDIA RTX 5090 (32 GB VRAM,
CUDA 13.3) sits idle. nvidia-container-toolkit is not installed.

Earlier this cycle, Phase 0 of an earlier plan
(`.opencode/plans/fastembed-gpu-migration.md`) eliminated the OOM that
triggered the original switch from `nomic-embed-text-v1.5` (768 d) to
`BAAI/bge-small-en-v1.5` (384 d). OOM is gone, but CPU saturation is the new
bottleneck. LM Studio was previously retired as the embedding backend (see
`.opencode/plans/embedding-migration-fastembed.md`); it is now being
migrated to llama.cpp in WSL for LLM inference, so reintroducing it as the
embedding backend is not on the table.

Goal: move embedding compute to the GPU via `fastembed-gpu` +
`CUDAExecutionProvider`, with hard-fail on missing GPU (per user decision).

### Confirmed decisions

| Question | Decision |
|---|---|
| Embedding backend | **FastEmbed GPU** (`fastembed-gpu` + `CUDAExecutionProvider`) |
| Embedding model | **BAAI/bge-small-en-v1.5** (384 d) — keep current |
| CPU fallback | **No** — hard-fail if GPU is unavailable |
| CUDA baseline | 12.8+ (required for RTX 5090 / Blackwell sm_120) |
| Host OS | Debian 13 (trixie); may run inside WSL2 |
| Order | Phase 1 (host toolkit) → Phase 2 (code) |
| LM Studio embeddings | **Rejected** — LM Studio migrates to llama.cpp in WSL |

### Phase 0 status — ✅ COMPLETE (6/6)

Verified 2026-07-05. 25 tests pass, `ruff check` clean. Both OOM sources
addressed:

- Per-chunk `ONNX InferenceSession` recreation → single `Embedder` per ingest
  run (`ingestion/ingest.py:177`).
- `all_chunks_map` holding the entire corpus in RAM → pickle cache in
  `qdrant_storage/_chunks_cache/`, streamed in Phase 1, reloaded per
  framework in Phase 4, cleaned in `finally` (`ingestion/ingest.py:7-53,
  108-124, 193-199, 274-277`).

### Plan execution status — ✅ FULLY COMPLETE

Verified 2026-07-05. All phases executed, additional discoveries and fixes
applied during implementation:

**Phase 1**: nvidia-container-toolkit 1.19.1 installed and configured on
Debian 13 / WSL2 host. `docker run --rm --gpus all nvidia/cuda:12.8.0 nvidia-smi`
shows RTX 5090 with driver 610.43.02 / CUDA 13.3.

**Phase 2**: All 6 code changes applied. 107 tests pass, `ruff check` clean.

**Discovered and fixed during implementation**:

1. **`libcudart.so.13` not in container** — nvidia-container-toolkit injects
   only driver-level libs (libcuda.so.1), not CUDA Runtime. Fix: multi-stage
   Dockerfile copies entire `/usr/local/cuda-13.0/targets/x86_64-linux/lib/`
   + cuDNN 9.x from `nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04` into
   `/usr/local/lib/cuda/` and `/usr/local/lib/cudnn/`, with `LD_LIBRARY_PATH`
   set accordingly. **Required for onnxruntime-gpu 1.27.0 built against CUDA 13.**

2. **cuDNN 9.x also needed** — same multi-stage provides it.

3. **fastembed 0.8.0 API change** — `OnnxTextEmbedding` no longer exposes
   `get_providers()` method, only `providers` attribute (set to resolved
   list after onnxruntime session init). Fix: `_validate_providers` reads
   `self._model.model.providers` (the list fastembed stores after resolving
   the requested providers against actual runtime availability). Tests in
   `tests/conftest.py` and `tests/test_embedder_local.py` updated to match.

**Final verification**:
- Container: `Up ... (healthy)`
- `GET /health` returns 200, model = `BAAI/bge-small-en-v1.5`
- `Embedder()._model.model.providers` = `['CUDAExecutionProvider']`
- Ingest perf: **1000 texts embedded in 1.076s ≈ 930 texts/sec** on RTX 5090
- 107/107 tests pass, `ruff check` clean
- Hard-fail: removing `deploy.resources` from compose makes
  `CudaNotAvailableError` propagate and container exits non-zero

---

## Target architecture

```
Host (Debian 13 / WSL2)
├── nvidia-driver (CUDA 13.3)              [installed]
├── nvidia-container-toolkit               [install in Phase 1]
├── Docker daemon (nvidia runtime)         [configure in Phase 1]
│
└── Container "lore" (--gpus all)
    ├── python:3.14-slim base
    ├── fastembed-gpu 0.8.0                [Phase 2]
    │   └── onnxruntime-gpu 1.18.0         [transitive]
    │       └── CUDAExecutionProvider       [injected by nvidia-container-toolkit]
    ├── Embedder(model, providers=["CUDAExecutionProvider"])
    │   └── hard-fail if CUDA not available
    └── (rest of Lore — unchanged)
```

---

## Phase 1 — Install nvidia-container-toolkit (host)

**Goal**: enable Docker to pass the GPU through to the Lore container.
**Time**: 10–15 min. Requires `sudo` and a Docker daemon restart.

### 1.1 Verify host prerequisites

```bash
lspci | grep -i nvidia
nvidia-smi
# Expected: RTX 5090 listed, driver 570+ (CUDA 13.3 user-mode)
```

**WSL2 nuance**: the driver comes from the Windows host. Confirm with
`ls /usr/lib/wsl/drivers/` and that `nvidia-smi` reports the Windows driver
version. If not visible, update the Windows NVIDIA driver and run
`wsl --update` from PowerShell, then re-enter the WSL distro.

### 1.2 Install (Debian 13 / trixie)

```bash
# 1. GPG key
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

# 2. Three repos (libnvidia-container, nvidia-container-runtime, nvidia-docker)
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

curl -s -L https://nvidia.github.io/nvidia-container-runtime/stable/deb/nvidia-container-runtime.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-runtime.list

curl -s -L https://nvidia.github.io/nvidia-docker/stable/deb/nvidia-docker.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 3. Install
sudo apt update
sudo apt install -y nvidia-container-toolkit

# 4. Register runtime with Docker daemon
sudo nvidia-ctk runtime configure --runtime=docker
# Patches /etc/docker/daemon.json: adds "runtimes": {"nvidia": {...}}

# 5. Restart Docker
sudo systemctl restart docker
```

### 1.3 Verify

```bash
# (A) Pull + run with GPU passthrough
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
# Expected: table with RTX 5090, driver version, CUDA Version

# (B) Devices visible inside container
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 \
  bash -c "ls /dev/nvidia* && ldconfig -p | grep -i cuda | head -3"
# Expected: /dev/nvidia0, /dev/nvidiactl, /dev/nvidia-uvm

# (C) Toolkit self-check
nvidia-container-cli list
```

**Acceptance**: all three pass. On failure, check
`journalctl -u docker --no-pager | tail -50`.

### 1.4 Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `could not select device driver "" with capabilities: [[gpu]]` | toolkit not registered | repeat 1.2 step 4 |
| `nvidia-container-cli: requirement error: no NVIDIA devices were found` | driver not loaded / WSL mismatch | reboot host, update driver |
| `libcuda.so.1: cannot open shared object file` | CUDA libs not injected | update toolkit to latest |
| WSL2: `nvidia-smi` shows 0 GPUs | Windows driver < 560 | update Windows NVIDIA driver |

---

## Phase 2 — Code changes (Lore)

**Goal**: switch embedding to GPU via `fastembed-gpu` with hard-fail on
missing CUDA.
**Time**: 30–60 min (edits + tests + verify).

### 2.1 Dependencies

**`pyproject.toml`** (replace one line):

```toml
dependencies = [
    # ... unchanged ...
    "fastembed-gpu>=0.8.0",   # was: "fastembed>=0.4.0"
    # ... unchanged ...
]
```

```bash
uv lock
```

**Pre-flight check for Python 3.14 wheel**:
`fastembed-gpu` pulls `onnxruntime-gpu==1.18.0` from the Azure
`onnxruntime-cuda-12` feed. Wheels for Python 3.14 may not exist; if
`uv pip install --dry-run fastembed-gpu` (or `pip download fastembed-gpu
--no-deps -d /tmp/wheels`) does not produce a `cp314` wheel, fall back to
Python 3.12 in a multi-stage Dockerfile.

### 2.2 `docs_shared/embedder.py`

Replace the existing 38-line file with:

```python
from __future__ import annotations

import asyncio
import os
from functools import partial
from threading import Lock
from typing import Sequence

from fastembed import TextEmbedding

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_PROVIDERS: tuple[str, ...] = ("CUDAExecutionProvider",)


class CudaNotAvailableError(RuntimeError):
    """Requested ONNX execution provider is not available in the runtime."""


class Embedder:
    """In-process ONNX embedding via fastembed (BAAI/bge-small-en-v1.5)."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        cache_dir: str | None = None,
        batch_size: int = 64,
        providers: Sequence[str] | None = None,
    ) -> None:
        if providers is None:
            env = os.environ.get("EMBEDDING_PROVIDERS", ",".join(DEFAULT_PROVIDERS))
            providers = tuple(p.strip() for p in env.split(",") if p.strip())

        kwargs: dict = {
            "model_name": model_name,
            "batch_size": batch_size,
            "providers": list(providers),
        }
        if cache_dir:
            kwargs["cache_dir"] = cache_dir

        self._model = TextEmbedding(**kwargs)
        self._lock = Lock()
        self._validate_providers(providers)

    def _validate_providers(self, requested: Sequence[str]) -> None:
        available = tuple(self._model.model.get_providers())
        missing = [p for p in requested if p not in available]
        if missing:
            raise CudaNotAvailableError(
                f"Requested ONNX provider(s) {missing!r} not available. "
                f"Available: {available!r}. "
                f"Check nvidia-container-toolkit (Phase 1) and host driver."
            )

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return [e.tolist() for e in self._model.embed(list(texts))]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self.embed_sync, texts))

    async def embed_one(self, text: str) -> list[float]:
        vecs = await self.embed([text])
        return vecs[0]
```

**`EMBEDDING_PROVIDERS` env semantics**:
- `CUDAExecutionProvider` (default) — requires GPU
- `CPUExecutionProvider` — dev fallback (not used in compose)
- `CUDAExecutionProvider,CPUExecutionProvider` — onnxruntime picks first
  available

### 2.3 `docs_shared/exceptions.py`

If the file does not exist, create it:

```python
"""Custom exception hierarchy for the lore project."""


class LoreError(Exception):
    """Base class for all lore-specific errors."""


class CudaNotAvailableError(LoreError, RuntimeError):
    """ONNX execution provider (e.g. CUDA) is not available in the runtime.

    Raised by Embedder.__init__ when the requested provider cannot be
    initialised. Indicates a host-level misconfiguration
    (nvidia-container-toolkit not installed, driver mismatch, no GPU).
    """
```

If the file already exists with other classes, append
`CudaNotAvailableError` (multiple inheritance preserves any existing
ordering).

### 2.4 `docker-compose.yml`

Add the GPU reservation block to the `lore` service:

```yaml
services:
  lore:
    image: lore
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Compose version note**: the `deploy.resources.reservations.devices`
syntax is for `docker compose` v2+. If the host has the legacy
`docker-compose` v1 binary, use `runtime: nvidia` at the service root
instead. Check with `docker compose version` (v2.x) vs
`docker-compose --version` (v1.x).

### 2.5 `.env.example`

Append:

```bash
# ONNX execution providers for fastembed (comma-separated).
# Default: CUDAExecutionProvider (hard-fail if GPU absent).
# To allow CPU fallback in dev: EMBEDDING_PROVIDERS=CPUExecutionProvider
EMBEDDING_PROVIDERS=CUDAExecutionProvider

# (Optional) larger model — requires re-ingest after change.
# EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
# EMBEDDING_DIM=768
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384
```

### 2.6 `tests/test_embedder_local.py`

Add four new tests. Keep the existing
`test_embedder_initialization_with_cache` (it already asserts
`batch_size=64`).

```python
import os

from docs_shared.embedder import CudaNotAvailableError, Embedder


def test_embedder_default_providers():
    """Without EMBEDDING_PROVIDERS env, default is CUDAExecutionProvider."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_model.get_providers.return_value = [
                "CUDAExecutionProvider", "CPUExecutionProvider",
            ]
            mock_cls.return_value = mock_model
            Embedder()
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == ["CUDAExecutionProvider"]


def test_embedder_providers_from_env():
    """EMBEDDING_PROVIDERS env var is parsed and passed to TextEmbedding."""
    with patch.dict(os.environ, {
        "EMBEDDING_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider"
    }):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_model.get_providers.return_value = [
                "CUDAExecutionProvider", "CPUExecutionProvider",
            ]
            mock_cls.return_value = mock_model
            Embedder()
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == [
                "CUDAExecutionProvider", "CPUExecutionProvider",
            ]


def test_embedder_validates_providers_hard_fail():
    """Requested provider not in available -> CudaNotAvailableError."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_model.get_providers.return_value = ["CPUExecutionProvider"]
            mock_cls.return_value = mock_model

            with pytest.raises(CudaNotAvailableError) as exc_info:
                Embedder()
            assert "CUDAExecutionProvider" in str(exc_info.value)
            assert "CPUExecutionProvider" in str(exc_info.value)


def test_embedder_providers_explicit_override():
    """providers= kwarg overrides env var."""
    with patch.dict(os.environ, {"EMBEDDING_PROVIDERS": "CUDAExecutionProvider"}):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_model.get_providers.return_value = ["CPUExecutionProvider"]
            mock_cls.return_value = mock_model
            Embedder(providers=["CPUExecutionProvider"])
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == ["CPUExecutionProvider"]
```

### 2.7 Documentation updates (post-implementation)

| File | Change |
|------|--------|
| `docs/areas/docker.md` | New "GPU support" section: requirement of `nvidia-container-toolkit`, link to Phase 1 instructions |
| `docs/areas/ingestion.md` | Embedder section: add "Providers: CUDAExecutionProvider (default, hard-fail on miss), env `EMBEDDING_PROVIDERS`" |
| `docs/architecture.md` | Note GPU as required dependency for the container image |
| `docs/troubleshooting.md` | New entry: "CUDA provider unavailable" with Phase 1 diagnostic pointers |

---

## Verify

### Lint and tests

```bash
make test
# Expected: 25 (Phase 0) + 4 (new providers) = 29 passed

uv run ruff check
# Expected: All checks passed!
```

### Build and run

```bash
make rebuild
make up

# GPU devices visible
docker exec lore bash -c "ls /dev/nvidia* 2>&1"
# Expected: /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm

# CUDA provider available
docker exec lore python -c \
  "from docs_shared.embedder import Embedder; e=Embedder(); print(e._model.model.get_providers())"
# Expected: ['CUDAExecutionProvider', 'CPUExecutionProvider']
```

### Ingest performance

```bash
time make prepare
time make ingest-clear
# In another terminal: watch -n 1 nvidia-smi
# Expected during embed phase:
#   - GPU utilization 30-80%
#   - Host CPU utilization well below 100%
#   - 5-20× speedup vs CPU ingest
```

### Hard-fail on missing GPU

```bash
make down
docker compose up lore
# Expected:
#   - Container fails at startup
#   - Logs show CudaNotAvailableError
#   - Exit code != 0
#   - Healthcheck does not pass
```

### Acceptance criteria

| # | Criterion | How to check |
|---|-----------|--------------|
| 1 | Phase 1: nvidia-container-toolkit installed | `apt list --installed \| grep nvidia-container-toolkit` |
| 2 | Phase 1: GPU passthrough works in test container | `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi` |
| 3 | Phase 2.1: `fastembed-gpu` in dependencies | `grep fastembed-gpu pyproject.toml uv.lock` |
| 4 | Phase 2.2: Embedder accepts `providers` kwarg | `test_embedder_default_providers` passes |
| 5 | Phase 2.2: Embedder reads `EMBEDDING_PROVIDERS` env | `test_embedder_providers_from_env` passes |
| 6 | Phase 2.2: Hard-fail on missing CUDA | `test_embedder_validates_providers_hard_fail` passes |
| 7 | Phase 2.4: compose requests GPU | `docker compose config \| grep nvidia` |
| 8 | Phase 2: `make test` — 29 tests pass | `pytest` |
| 9 | Phase 2: `ruff check` clean | `uv run ruff check` |
| 10 | Phase 2: container sees `/dev/nvidia*` | `docker exec lore ls /dev/nvidia*` |
| 11 | Phase 2: providers list = `['CUDAExecutionProvider', 'CPUExecutionProvider']` | `docker exec lore python -c "..."` |
| 12 | Phase 2: `make ingest-clear` completes | `time make ingest-clear` |
| 13 | Phase 2: GPU util >30% during ingest | `nvidia-smi` in parallel terminal |
| 14 | Phase 2: host CPU NOT at 100% during ingest | `htop` |
| 15 | Phase 2: hard-fail works | `docker compose up lore` without GPU → exit non-zero |

---

## Rollback

### Roll back Phase 2 (code only)

```bash
git checkout -- pyproject.toml uv.lock docs_shared/embedder.py docs_shared/exceptions.py
git checkout -- docker-compose.yml .env.example tests/test_embedder_local.py
uv lock
make rebuild
make up
# Back to CPU fastembed
```

### Roll back Phase 1 (toolkit removal)

```bash
# Remove GPU reservation from compose if not rolling back code
# (edit docker-compose.yml: remove deploy.resources block)

# Full toolkit removal
sudo apt remove --purge nvidia-container-toolkit
sudo rm /etc/apt/sources.list.d/nvidia-{container-toolkit,container-runtime,docker}.list
sudo apt update
sudo nvidia-ctk runtime configure --runtime=docker --remove
# or manually edit /etc/docker/daemon.json
sudo systemctl restart docker
```

### Emergency fallback to LM Studio (not recommended)

This would take 2–3 hours of coding from scratch and is not on the table
because LM Studio is being migrated to llama.cpp in WSL. Outline only:

1. `docs_shared/lmstudio_client.py` — httpx client for
   `http://host.docker.internal:1234/v1/embeddings`.
2. Refactor `docs_shared/embedder.py` to a backend facade with
   `EMBEDDING_BACKEND=fastembed|lmstudio`.
3. Add `/health` LM Studio reachability check.
4. Plumb `host.docker.internal` (works on Docker Desktop; on Linux use
   `network_mode: host` or `extra_hosts`).
5. Document the SPOF.

---

## Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| 1 | Python 3.14 wheel for `onnxruntime-gpu` missing | Medium | Phase 2 blocked | Dry-run `uv pip install fastembed-gpu`; if no cp314, build from source or use Python 3.12 in multi-stage Dockerfile |
| 2 | RTX 5090 (sm_120) not supported by onnxruntime 1.18.0 | Low | Phase 2 blocked | onnxruntime 1.18.0 ships CUDA 12.x EP with Blackwell support; if not, bump to 1.19+ |
| 3 | Legacy `docker-compose` v1 ignores `deploy.resources` | Medium | GPU not requested | Check `docker compose version`; if v1, use `runtime: nvidia` |
| 4 | WSL2 driver mismatch | Medium | GPU invisible in WSL | Update Windows NVIDIA driver, `wsl --update`, restart WSL |
| 5 | Hard-fail blocks local dev without GPU | Medium | DX | Document `EMBEDDING_PROVIDERS=CPUExecutionProvider` in `.env.example` (commented) |
| 6 | `fastembed-gpu` wheels only from Azure feed | Low | Install time | Document in plan; CI/CD may need separate index URL |
| 7 | Forgot `make ingest-clear` after model swap | Low | Mixed embeddings | `.model_info.json` drift detection logs warning on startup |
| 8 | CUDA 13 host driver vs CUDA 12 onnxruntime wheels | Medium | Init failure | onnxruntime 1.18.0 targets CUDA 12 runtime ABI; host 13.3 driver is backward compatible. If mismatch: update toolkit to latest |

---

## Out of scope

- Multi-GPU / MIG slicing.
- Quantized embedding models (ONNX INT8) for further speedup.
- Replacing TF-IDF sparse vectors with a GPU alternative.
- Formal CPU vs GPU benchmark suite (we do time-based sanity checks only).
- Auto-fallback to CPU when GPU is absent (per user decision — hard-fail).
- LLM inference migration: LM Studio → llama.cpp in WSL (separate project).
- Embedding model drift detection across bge-small / nomic-embed (only if
  the model is swapped in the future).
- Bundling CUDA libs inside the image (we rely on runtime injection via
  nvidia-container-toolkit).

---

## Execution checklist

```
[ ] Phase 1 (host, ~15 min, sudo) — NOT YET DONE
    [ ] Verify nvidia-smi, lspci
    [ ] Install GPG key + 3 repos
    [ ] apt install nvidia-container-toolkit
    [ ] nvidia-ctk runtime configure
    [ ] systemctl restart docker
    [ ] Verify: docker run --rm --gpus all nvidia/cuda:12.8.0 nvidia-smi

[x] Phase 2 (code) — COMPLETE 2026-07-05
    [x] pyproject.toml: fastembed -> fastembed-gpu
    [x] uv lock
    [x] docs_shared/embedder.py: +providers, +_validate_providers, +CudaNotAvailableError
    [x] docs_shared/exceptions.py: +CudaNotAvailableError
    [x] docker-compose.yml: +deploy.resources
    [x] .env.example: +EMBEDDING_PROVIDERS
    [x] tests/test_embedder_local.py: +4 tests
    [x] make test (107 pass)
    [x] uv run ruff check (clean)
    [ ] make rebuild
    [ ] make up
    [ ] docker exec lore python -c "get_providers()"
    [ ] time make ingest-clear
    [ ] nvidia-smi in parallel: GPU util >30%
    [ ] hard-fail test: docker compose up lore -> exit != 0

[x] Documentation — COMPLETE 2026-07-05
    [x] docs/areas/docker.md: +GPU support section
    [x] docs/areas/ingestion.md: +Providers mention
    [x] docs/architecture.md: GPU as required dep
    [x] docs/troubleshooting.md: +CUDA unavailable

[ ] Final smoke test (after Phase 1)
    [ ] make test
    [ ] uv run ruff check
    [ ] make rebuild && make up
    [ ] curl http://localhost:8000/health (expect 200)
    [ ] make ingest-clear (expect success)
    [ ] curl -X POST http://localhost:8000/search -d '{"query": "test"}' (expect results)
```
