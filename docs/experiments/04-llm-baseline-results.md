# Результаты эксперимента 4: воспроизводимая базовая оценка LLM

- Дата: 2026-10-25 20:21
- Машина: arm64, macOS-15.7.4-arm64-arm-64bit
- Провайдер: ollama
- Версия сервера: 0.35.1
- Модель: qwen3:8b
- API URL: http://127.0.0.1:11500/v1
- Таймаут запроса: 180 с
- Параметры генерации: temperature=0; классификация max_tokens=100; генерация max_tokens=350 (см. `ai_clients/ollama.py`)
- Прогрев: отдельный запрос для классификатора и генератора перед измерением
- Ошибки прогрева: 2
- Ошибки запросов/формата в тестовых случаях: 1

## Классификация

- Точных совпадений по всем полям: 4/10
- Среднее время успешного запроса: 80.3 с

| Поле | Совпадений |
|---|---:|
| `category` | 10/10 |
| `priority` | 6/10 |
| `sentiment` | 10/10 |
| `wants_human` | 7/10 |

| Вопрос | Ожидалось | Получено | Ошибки | Время |
|---|---|---|---|---:|
| Когда вернутся деньги за отменённый заказ? | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 79.4 с |
| С меня списали деньги два раза за один заказ!!! Верните немедленно | `{"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": false}` | `{"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": true}` | wants_human: ожидалось False, получено True | 62.2 с |
| Можно ли оплатить заказ частями? | `{"category": "billing", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false}` | priority: ожидалось 'low', получено 'normal' | 80.5 с |
| Где сейчас мой заказ? Номер 48213 | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 77.1 с |
| ЗАКАЗ ОПАЗДЫВАЕТ УЖЕ НА НЕДЕЛЮ, ЭТО ИЗДЕВАТЕЛЬСТВО | `{"category": "delivery", "priority": "normal", "sentiment": "negative", "wants_human": false}` | `{"category": "delivery", "priority": "critical", "sentiment": "negative", "wants_human": true}` | priority: ожидалось 'normal', получено 'critical'; wants_human: ожидалось False, получено True | 102.7 с |
| Доставляете ли вы в Казань? | `{"category": "delivery", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false}` | priority: ожидалось 'low', получено 'normal' | 78.0 с |
| Не могу войти в аккаунт, пишет неверный пароль | `{"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false}` | `{"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false}` | — | 77.2 с |
| Кто-то зашёл в мой аккаунт и поменял почту, срочно помогите | `{"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": false}` | `{"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": true}` | wants_human: ожидалось False, получено True | 60.7 с |
| Позовите живого оператора, бот ничего не понимает | `{"category": "other", "priority": "normal", "sentiment": "negative", "wants_human": true}` | `{"category": "other", "priority": "low", "sentiment": "negative", "wants_human": true}` | priority: ожидалось 'normal', получено 'low' | 106.4 с |
| Вы работаете в праздники? | `{"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false}` | `{"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false}` | — | 78.9 с |

## Генерация ответов

- Сценариев пройдено: 2/3
- Среднее время успешного запроса: 101.9 с

| Сценарий | Ожидаемые свойства | Результат модели | Проверка | Время |
|---|---|---|---|---:|
| Ответ есть в документах | `{"answer_present": true, "source_ids": ["refund-policy"], "needs_escalation": false, "required_facts": ["10 рабочих дней", "исходный способ оплаты"]}` | `{"answer": "Деньги за отменённый заказ возвращаются в течение 10 рабочих дней на исходный способ оплаты.", "source_ids": ["refund-policy"], "needs_escalation": false}` | пройдено | 130.4 с |
| Информации недостаточно | `{"answer_present": false, "source_ids": [], "needs_escalation": true, "required_facts": []}` | `{"answer": null, "source_ids": [], "needs_escalation": true}` | пройдено | 73.3 с |
| Несколько документов | `{"answer_present": true, "source_ids": ["delivery-price", "delivery-time"], "needs_escalation": false, "required_facts": ["350 рублей", "3-5 рабочих дней"]}` | ошибка | Ошибка запроса/формата: Сервер модели вернул ошибку: ReadTimeout('') | — |

## Критерий результата

Прогон получает статус **ПРОЙДЕН** только если версия сервера зафиксирована, все метки классификации совпали с эталоном, все три сценария генерации выполнили ожидаемые условия, а прогрев прошёл без ошибок. Несовпадение модели сохраняется в отчёте и возвращает ненулевой код завершения.

**Итог:** НЕ ПРОЙДЕН

### Ошибки прогрева

- Классификатор: Сервер модели вернул ошибку: ReadTimeout('')
- Генератор: Сервер модели вернул ошибку: ReadTimeout('')
