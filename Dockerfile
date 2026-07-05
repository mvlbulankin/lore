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

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/ingestion" \
    HF_HOME="/data/hf_cache"

RUN mkdir -p /data /home/lore/.cache && useradd -r -u 1000 -d /home/lore -s /bin/false lore && chown -R lore:lore /data /home/lore

USER lore

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
