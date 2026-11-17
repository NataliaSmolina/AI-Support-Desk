FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev --package support-bot

CMD ["uv", "run", "--no-sync", "--package", "support-bot", "python", "-m", "support_bot.main"]