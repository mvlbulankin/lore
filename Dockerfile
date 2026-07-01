FROM python:3.14-slim

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

RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app

# Run as root to allow writing to mounted volumes (host-owned data dir).
# For local dev tool this is acceptable; for production use UID-mapped volumes.

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/ingestion"

RUN mkdir -p /data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
