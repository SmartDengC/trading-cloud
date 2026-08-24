FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY sql ./sql
CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--proxy-headers"]

