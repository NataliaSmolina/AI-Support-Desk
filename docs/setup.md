# Запуск проекта с нуля

Нужны **Docker** и **uv**. Все сервисы запускаются в контейнерах с закреплёнными версиями.

## Занятые порты на компьютере

| Сервис | Файл | Порт |
|---|---|---|
| TEI (bge-m3) | `infra/tei/compose.yml` | 8081 |
| LLM (Ollama + qwen3:8b) | `infra/llm/compose.yml` | 11500 |

## 1. Docker

Docker Desktop: https://www.docker.com/products/docker-desktop

Docker Desktop → Settings → Resources → Memory: не меньше 12 ГБ, модели вместе занимают около 8 ГБ.

## 2. uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 3. Настройки и тесты

```bash
cp .env.example .env
uv sync
uv run pytest
```

## 4. Запуск сервисов

Всё сразу:

```bash
docker compose up -d
```

Или по одному: `docker compose up -d tei`, `docker compose up -d llm llm-pull`.

Готовность:

```bash
docker compose logs -f tei        # ждать строку Ready (первый раз ~2 ГБ)
docker compose logs -f llm-pull   # ждать строку success (первый раз ~5 ГБ)
```

Ctrl+C — выйти из логов.

## 5. Закрепить версию LLM-сервера (один раз, делает один человек)

```bash
docker compose exec llm ollama --version
```

Впишите версию в `.env.example` вместо `latest`, например `LLM_IMAGE=ollama/ollama:0.12.3`, и закоммитьте.

## 6. Проверки на настоящих моделях

```bash
uv run python evals/check_embed.py      # шаг 2
uv run python evals/check_classify.py   # шаг 1
```

## 7. Telegram-бот

1. Получить токен у [@BotFather](https://t.me/BotFather) (`/newbot`).
2. Вписать его в `.env`: `BOT_TOKEN=...`. Файл `.env` в `.gitignore` — в git токен не попадёт.
3. Запустить:

```bash
uv run python -m support_bot.main
```

Остановить — Ctrl+C. Бот работает в режиме polling: сам спрашивает у Telegram новые сообщения, публичный адрес не нужен.


## Остановить

```bash
docker compose down
```

Скачанные модели остаются в томах Docker.

## Про скорость на Mac

Docker на Mac не использует графику чипа M1–M4, поэтому модели в контейнерах считают на процессоре, а TEI ещё и через эмуляцию x86. Это медленнее, результат тот же. Замеры записывайте с пометкой, на какой машине они сделаны.
