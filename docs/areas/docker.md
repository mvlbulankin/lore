# Docker

**Files:** `Dockerfile`, `docker-compose.yml`

## Image

Based on `python:3.14-slim` with `uv` copied from `ghcr.io/astral-sh/uv:latest`. Final image size is ~600-700MB (includes fastembed, onnxruntime, scikit-learn).

### Build Layers

1. Base Python 3.14 slim + uv
2. System deps: `curl` (for healthcheck)
3. Lock file sync: `uv sync --frozen` (cached layer)
4. Application code: `docs_shared/`, `ingestion/`, `app/`
5. Environment: `PYTHONPATH=/app:/app/ingestion`, `PATH` includes `.venv/bin`, `FASTEMBED_CACHE_PATH=/data/fastembed_cache`

### Entrypoint

```bash
python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
```

## Volume Mounts

| Mount | Direction | Purpose |
|-------|-----------|---------|
| `./data:/data` | read-write | Qdrant embedded storage + prepared documents + fastembed model cache |

The `data` directory on the host contains:
- `data/qdrant_storage/` — Qdrant embedded storage (vectors + sparse model)
- `data/prepared/` — prepared documents
- `data/fastembed_cache/` — fastembed ONNX model cache (downloaded on first use)

## Port Mapping

Container exposes port 8000, mapped to host port 8000. Server binds to `0.0.0.0`.

## Healthcheck

Docker healthcheck curls `http://localhost:8000/health` every 10s with 5s timeout and 5 retry attempts.

## PYTHONPATH

Set to `/app:/app/ingestion` so that:
- `docs_shared` is importable as a top-level package
- `ingestion/` modules (chunker, ingest) are importable directly
- `app/` is the uvicorn working directory

## GPU Support

The container requests GPU access via `deploy.resources.reservations.devices` in
`docker-compose.yml`. This requires `nvidia-container-toolkit` installed on the
host. Without it, the container will fail to start.

### Requirements

- NVIDIA driver on the host (CUDA 12.8+ for RTX 5090 / Blackwell sm_120)
- `nvidia-container-toolkit` package installed and registered with Docker daemon
- Docker daemon restarted after toolkit installation

### Installation (Debian 13 / trixie)

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

curl -s -L https://nvidia.github.io/nvidia-container-runtime/stable/deb/nvidia-container-runtime.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-runtime.list

curl -s -L https://nvidia.github.io/nvidia-docker/stable/deb/nvidia-docker.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Verification

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

### WSL2

The NVIDIA driver comes from the Windows host. Ensure Windows NVIDIA driver is
up to date, run `wsl --update` from PowerShell, then re-enter the WSL distro.

### CPU Fallback (Development)

To run without GPU, set `EMBEDDING_PROVIDERS=CPUExecutionProvider` in `.env`.
The default is `CUDAExecutionProvider` which hard-fails if GPU is unavailable.

## Security Notes

- Container runs as non-root user `lore`
- `/data` is chowned to `lore:lore`
- For host volumes with different UID, use Docker volume driver or `--user` flag
- No external network dependencies — embeddings are computed in-process
