# Результаты проверки шага 1 (определение темы)

- Дата: 2026-10-11 21:45
- Машина: arm64, macOS-15.7.4-arm64-arm-64bit
- Модель: qwen3:8b (http://127.0.0.1:11500/v1)
- Вопросов: 10, ошибок формата или связи: 0
- Среднее время ответа: 39.8 с

| Поле | Верно |
|---|---|
| category | 10 из 10 |
| priority | 6 из 10 |
| sentiment | 10 из 10 |
| wants_human | 7 из 10 |

| Вопрос | Ответ модели | Сравнение с ожидаемым | Время |
|---|---|---|---|
| Когда вернутся деньги за отменённый заказ? | {"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 32.5 с |
| С меня списали деньги два раза за один заказ!!! Верните немедленно | {"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": true} | wants_human: ждали False, получили True | 33.5 с |
| Можно ли оплатить заказ частями? | {"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": false} | priority: ждали low, получили normal | 37.9 с |
| Где сейчас мой заказ? Номер 48213 | {"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 32.2 с |
| ЗАКАЗ ОПАЗДЫВАЕТ УЖЕ НА НЕДЕЛЮ, ЭТО ИЗДЕВАТЕЛЬСТВО | {"category": "delivery", "priority": "critical", "sentiment": "negative", "wants_human": true} | priority: ждали normal, получили critical; wants_human: ждали False, получили True | 34.0 с |
| Доставляете ли вы в Казань? | {"category": "delivery", "priority": "normal", "sentiment": "calm", "wants_human": false} | priority: ждали low, получили normal | 44.3 с |
| Не могу войти в аккаунт, пишет неверный пароль | {"category": "account", "priority": "normal", "sentiment": "calm", "wants_human": false} | верно | 84.0 с |
| Кто-то зашёл в мой аккаунт и поменял почту, срочно помогите | {"category": "account", "priority": "critical", "sentiment": "negative", "wants_human": true} | wants_human: ждали False, получили True | 42.5 с |
| Позовите живого оператора, бот ничего не понимает | {"category": "other", "priority": "low", "sentiment": "negative", "wants_human": true} | priority: ждали normal, получили low | 28.3 с |
| Вы работаете в праздники? | {"category": "other", "priority": "low", "sentiment": "calm", "wants_human": false} | верно | 28.3 с |
