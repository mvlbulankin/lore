FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04 AS cuda-libs

# Stage 1: extract CUDA 13 Runtime + cuDNN 9 libraries that
# onnxruntime-gpu 1.27.0 needs. nvidia-container-toolkit injects only
# driver-level libs (libcuda.so.1), not CUDA Runtime / cuDNN.
# Copy the entire runtime lib dir rather than enumerating — onnxruntime
# pulls in libcudart, libcublas, libcublasLt, libcurand, libnccl,
# libnvjitlink, etc., and the exact set varies by version.
RUN mkdir -p /cuda-libs/cuda /cuda-libs/cudnn && \
    cp -P /usr/local/cuda-13.0/targets/x86_64-linux/lib/* /cuda-libs/cuda/ && \
    cp -P /usr/lib/x86_64-linux-gnu/libcudnn*.so* /cuda-libs/cudnn/

FROM python:3.14-slim

# Copy CUDA 13 Runtime + cuDNN 9 libs from the cuda-libs stage
COPY --from=cuda-libs /cuda-libs/cuda/ /usr/local/lib/cuda/
COPY --from=cuda-libs /cuda-libs/cudnn/ /usr/local/lib/cudnn/
RUN ldconfig

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .
COPY docs_shared/pyproject.toml docs_shared/

RUN uv sync --frozen

COPY docs_shared/ /app/docs_shared/
COPY ingestion/ /app/ingestion/
COPY app/ /app/app/

# Run as non-root user for security.
# /data is chowned so the lore user can write to mounted volumes.
# For host volumes with different UID, use Docker volume driver or --user flag.

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/ingestion" \
    FASTEMBED_CACHE_PATH="/data/fastembed_cache" \
    HF_HOME="/data/hf_cache" \
    LD_LIBRARY_PATH="/usr/local/lib/cuda:/usr/local/lib/cudnn:${LD_LIBRARY_PATH}"

RUN mkdir -p /data /home/lore/.cache && useradd -r -u 1000 -d /home/lore -s /bin/false lore && chown -R lore:lore /data /home/lore

USER lore

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
