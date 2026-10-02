# Запуск проекта с нуля

Нужны **Docker** и **uv**. Все сервисы запускаются в контейнерах с закреплёнными версиями.

## Занятые порты на компьютере

| Сервис | Файл | Порт |
|---|---|---|
| TEI (bge-m3) | `infra/tei/compose.yml` | 8081 |

## 1. Docker

Docker Desktop: https://www.docker.com/products/docker-desktop

Docker Desktop → Settings → Resources → Memory: не меньше 12 ГБ.

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

```bash
docker compose up -d tei
docker compose logs -f tei     # ждать строку Ready, затем Ctrl+C
```

При первом запуске TEI скачивает bge-m3 (около 2 ГБ).

## 5. Проверки на настоящих моделях

```bash
uv run python evals/check_embed.py
```

## Остановить

```bash
docker compose down
```

## Про скорость на Mac

Docker на Mac не использует графику чипа M1–M4, а образ TEI работает ещё и через эмуляцию x86. Это медленнее, результат тот же. Замеры записывайте с пометкой, на какой машине они сделаны.
