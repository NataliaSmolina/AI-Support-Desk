# Эксперимент 2. Шаг 1: модель определяет, о чём вопрос

## Цель

Проверить, что модель на ноутбуке определяет тему, срочность, настроение и просьбу позвать человека, отвечает строго в заданном формате и укладывается по времени.

## Как запускали

1. `docker compose up -d llm llm-pull` — сервер модели в контейнере (`infra/llm`, Ollama), порт 11500, модель qwen3:8b.
2. `uv run python evals/check_classify.py`.

Скрипт прогоняет 10 вопросов из `evals/data/classify_questions.json` и сравнивает ответ модели с ожидаемым.

Темы пока временные: billing, delivery, account, other. Позже их заменят темы из базы знаний.

## Результаты

См. [02-classify-results.md](02-classify-results.md) — файл создаётся скриптом.

## Выводы

# Результаты проверки шага 1 (определение темы)

- Дата: 2026-10-11 20:17
- Машина: arm64, macOS-15.7.4-arm64-arm-64bit
- Модель: qwen3:8b (http://127.0.0.1:11500/v1)
- Вопросов: 10, ошибок формата или связи: 0
- Среднее время ответа: 35.6 с

| Поле | Верно |
|---|---|
| category | 10 из 10 |
| priority | 6 из 10 |
| sentiment | 10 из 10 |
| wants_human | 7 из 10 |

| Вопрос | Ответ модели | Сравнение с ожидаемым | Время |
|---|---|---|---|
| Когда вернутся деньги за отменённый заказ? | {"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 53.2 с |
| С меня списали деньги два раза за один заказ!!! Верните немедленно | {"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": true} | wants_human: ждали False, получили True | 56.0 с |
| Можно ли оплатить заказ частями? | {"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false} | priority: ждали low, получили normal | 54.0 с |
| Где сейчас мой заказ? Номер 48213 | {"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 39.1 с |
| ЗАКАЗ ОПАЗДЫВАЕТ УЖЕ НА НЕДЕЛЮ, ЭТО ИЗДЕВАТЕЛЬСТВО | {"category": "delivery", "priority": "critical", "sentiment": "negative", "wants_human": true} | priority: ждали normal, получили critical; wants_human: ждали False, получили True | 25.2 с |
| Доставляете ли вы в Казань? | {"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false} | priority: ждали low, получили normal | 25.6 с |
| Не могу войти в аккаунт, пишет неверный пароль | {"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 22.3 с |
| Кто-то зашёл в мой аккаунт и поменял почту, срочно помогите | {"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": true} | wants_human: ждали False, получили True | 24.6 с |
| Позовите живого оператора, бот ничего не понимает | {"category": "other", "priority": "low", "sentiment": "negative", "wants_human": true} | priority: ждали normal, получили low | 22.4 с |
| Вы работаете в праздники? | {"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false} | верно | 33.4 с |
