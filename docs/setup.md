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

## Явный выбор LLM и проверка перед запуском (неделя 5)

В существующий `.env` добавьте настройки из блока LLM в `.env.example`.
Не копируйте весь файл поверх своего `.env`: там могут быть токены и настройки БД.

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11500/v1
LLM_MODEL=qwen3:8b
LLM_HEALTH_TIMEOUT_S=5
```

Провайдер больше не определяется по номеру порта. Для нативного Ollama на
другом порту достаточно изменить URL, оставив `LLM_PROVIDER=ollama`.
`openai` выбирает уже существующий OpenAI-совместимый транспорт; миграция сервера не требуется.

### Самостоятельная проверка

Все команды выполняются из корня проекта. Переменные перед командой действуют
только для этого запуска и имеют приоритет над `.env`.

1. Запустите Ollama и дождитесь окончания загрузки модели:

   ```bash
   docker compose up -d llm llm-pull
   docker compose logs -f llm-pull
   ```

2. Выполните быструю проверку:

   ```bash
   uv run python -m ai_clients.readiness
   ```

   Ожидается `API доступен, модель 'qwen3:8b' найдена` и код выхода 0.
   Проверка только читает список установленных моделей. Она не загружает модель
   в память и не гарантирует успешную генерацию. Worker и baseline выполняют её
   автоматически до обработки обращений и прогрева соответственно.

3. Проверьте недоступный адрес, не останавливая рабочий сервер:

   ```bash
   LLM_BASE_URL=http://127.0.0.1:1/v1 uv run python -m ai_clients.readiness
   ```

   Ожидается `Не удалось подключиться к LLM` и код выхода 1.

4. Проверьте отсутствующую модель:

   ```bash
   LLM_MODEL=missing-model-for-check:never uv run python -m ai_clients.readiness
   ```

   Ожидается сообщение об отсутствующей модели и код выхода 1. Ничего не скачивается.

5. Проверьте ошибку настройки:

   ```bash
   LLM_PROVIDER=typo uv run python -m ai_clients.readiness
   ```

   Ожидается ошибка валидации `llm_provider`, запрос к серверу не выполняется.

6. Автоматические проверки без Docker и модели:

   ```bash
   uv run pytest libs/ai-clients/tests evals/tests -q
   ```

   Покрыты разные порты и провайдеры, отказ соединения, таймаут, HTTP-ошибка,
   некорректный ответ и отсутствие модели.

7. При желании проверьте реальную генерацию полным baseline (может занять много минут):

   ```bash
   uv run python evals/check_llm_baseline.py --output /tmp/week05-llm-baseline.md
   ```

   Исторический отчёт не перезаписывается. Ненулевой код после прогона может
   означать несовпадение классификации с эталоном, а не проблему подключения.
   `--provider` переопределяет `LLM_PROVIDER` только для baseline.

Прямые вызовы `LlmClassifier`, `LlmAnswerGenerator` и `LLMClient` теперь по умолчанию
используют Ollama независимо от URL. Для OpenAI-совместимого API передавайте
`provider="openai"` явно. Проверка готовности доступна отдельно как `check_llm_ready`.
