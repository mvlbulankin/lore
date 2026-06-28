FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock .
COPY docs_shared/pyproject.toml docs_shared/

RUN uv sync --frozen

COPY docs_shared/ /app/docs_shared/
COPY ingestion/ /app/ingestion/
COPY app/ /app/app/

RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
