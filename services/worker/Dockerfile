FROM python:3.12-slim-bookworm

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=60 \
    UV_HTTP_RETRIES=5 \
    UV_CONCURRENT_DOWNLOADS=4 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package support-worker && useradd --create-home --uid 10001 app \
    && install -d -o app -g app /home/app/.cache/huggingface

USER app
CMD ["support-worker"]
