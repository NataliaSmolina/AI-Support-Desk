# Результаты эксперимента 4: воспроизводимая базовая оценка LLM

- Дата: 2026-10-18 15:20
- Машина: arm64, macOS-15.7.4-arm64-arm-64bit
- Провайдер: ollama
- Версия сервера: 0.35.1
- Модель: qwen3:8b
- API URL: http://127.0.0.1:11500/v1
- Таймаут запроса: 180 с
- Параметры генерации: temperature=0; классификация max_tokens=100; генерация max_tokens=350 (см. `ai_clients/ollama.py`)
- Прогрев: отдельный запрос для классификатора и генератора перед измерением
- Ошибки прогрева: 0
- Ошибки запросов/формата в тестовых случаях: 0

## Классификация

- Точных совпадений по всем полям: 4/10
- Среднее время успешного запроса: 51.8 с

| Поле | Совпадений |
|---|---:|
| `category` | 10/10 |
| `priority` | 6/10 |
| `sentiment` | 10/10 |
| `wants_human` | 7/10 |

| Вопрос | Ожидалось | Получено | Ошибки | Время |
|---|---|---|---|---:|
| Когда вернутся деньги за отменённый заказ? | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 50.7 с |
| С меня списали деньги два раза за один заказ!!! Верните немедленно | `{"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": false}` | `{"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": true}` | wants_human: ожидалось False, получено True | 61.1 с |
| Можно ли оплатить заказ частями? | `{"category": "billing", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | priority: ожидалось 'low', получено 'normal' | 65.6 с |
| Где сейчас мой заказ? Номер 48213 | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 67.9 с |
| ЗАКАЗ ОПАЗДЫВАЕТ УЖЕ НА НЕДЕЛЮ, ЭТО ИЗДЕВАТЕЛЬСТВО | `{"category": "delivery", "priority": "normal", "sentiment": "negative", "wants_human": false}` | `{"category": "delivery", "priority": "critical", "sentiment": "negative", "wants_human": true}` | priority: ожидалось 'normal', получено 'critical'; wants_human: ожидалось False, получено True | 65.4 с |
| Доставляете ли вы в Казань? | `{"category": "delivery", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | priority: ожидалось 'low', получено 'normal' | 44.1 с |
| Не могу войти в аккаунт, пишет неверный пароль | `{"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 45.9 с |
| Кто-то зашёл в мой аккаунт и поменял почту, срочно помогите | `{"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": false}` | `{"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": true}` | wants_human: ожидалось False, получено True | 32.6 с |
| Позовите живого оператора, бот ничего не понимает | `{"category": "other", "priority": "normal", "sentiment": "negative", "wants_human": true}` | `{"category": "other", "priority": "low", "sentiment": "negative", "wants_human": true}` | priority: ожидалось 'normal', получено 'low' | 41.7 с |
| Вы работаете в праздники? | `{"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false}` | — | 43.1 с |

## Генерация ответов

- Сценариев пройдено: 3/3
- Среднее время успешного запроса: 61.4 с

| Сценарий | Ожидаемые свойства | Результат модели | Проверка | Время |
|---|---|---|---|---:|
| Ответ есть в документах | `{"answer_present": true, "source_ids": ["refund-policy"], "needs_escalation": false}` | `{"answer": "Деньги за отменённый заказ возвращаются в течение 10 рабочих дней на исходный способ оплаты.", "source_ids": ["refund-policy"], "needs_escalation": false}` | пройдено | 62.1 с |
| Информации недостаточно | `{"answer_present": false, "source_ids": [], "needs_escalation": true}` | `{"answer": null, "source_ids": [], "needs_escalation": true}` | пройдено | 31.9 с |
| Несколько документов | `{"answer_present": true, "source_ids": ["delivery-price", "delivery-time"], "needs_escalation": false}` | `{"answer": "Стоимость доставки в Казань составляет 350 рублей. Срок доставки в Казань составляет 3–5 рабочих дней.", "source_ids": ["delivery-price", "delivery-time"], "needs_escalation": false}` | пройдено | 90.1 с |

## Критерий результата

Прогон получает статус **ПРОЙДЕН** только если версия сервера зафиксирована, все метки классификации совпали с эталоном, все три сценария генерации выполнили ожидаемые условия, а прогрев прошёл без ошибок. Несовпадение модели сохраняется в отчёте и возвращает ненулевой код завершения.

**Итог:** НЕ ПРОЙДЕН
