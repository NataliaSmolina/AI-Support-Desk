# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY . .
RUN uv sync --frozen --no-dev --package kb-index

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/services/kb-index/src:/app/libs/ai-clients/src"

WORKDIR /app

RUN useradd --create-home --uid 10001 app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/services/kb-index/src /app/services/kb-index/src
COPY --from=builder /app/libs/ai-clients/src /app/libs/ai-clients/src

USER app

CMD ["python", "-m", "kb_index"]
