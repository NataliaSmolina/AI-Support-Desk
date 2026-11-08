"""Тексты сообщений бота."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.utils.formatting import Bold, Text

START = (
    "AI-Support-Desk"
)

HELP = (
    "Как пользоваться ботом:\n"
    "— напишите свой вопрос одним сообщением;\n"
    "— ответ придёт в этот чат;\n"
    "— /status покажет ваши обращения и их статус.\n\n"
    "Фото и файлы пока не обрабатываются — опишите вопрос текстом."
)

ONLY_TEXT = "Пока я понимаю только текст. Опишите, пожалуйста, вопрос словами."

def accepted(ticket_id: int | None) -> str:
    """Ответ на вопрос клиента: подтверждаем получение, ничего не обещаем. None – база не подключена."""
    if ticket_id is None:
        return "Вопрос получен. Ответ придёт в этот чат."
    return f"Вопрос получен, номер обращения #{ticket_id}. Ответ придёт в этот чат."

# База недоступна: вопрос не сохранился, клиент должен знать, что ждать нечего
SAVE_FAILED = "Не удалось принять вопрос. Попробуйте, пожалуйста, ещё раз через пару минут."

# Клиент прислал фото или файл с подписью: подпись приняли, само вложение – нет
ATTACHMENT_IGNORED = "⚠️ Вложение (фото или файл) не обрабатывается, учтён только текст подписи."

# --- Группа операторов ---

# Заглушка, пока worker не пишет настоящие черновики
FAKE_DRAFT = "Это тестовый черновик ответа. Настоящий напишет worker."

BUTTON_SEND = "✅ Отправить"
BUTTON_EDIT = "✏️ Исправить"


def card(question: str, draft: str, ticket_id: int | None = None) -> str:
    """Карточка для оператора: номер тикета, вопрос клиента и черновик ответа."""
    text = f"❓ Вопрос клиента:\n{question}\n\n📝 Черновик ответа:\n{draft}"
    if ticket_id is None:
        return text
    return f"🎫 Тикет #{ticket_id}\n\n{text}"


def card_sent(card_text: str, operator: str, *, history_saved: bool) -> str:
    """Добавляет имя оператора и результат сохранения ответа."""
    if history_saved:
        status = "✅ Отправлено и сохранено"
    else:
        status = "⚠️ Отправлено, история не сохранена"
    return f"{card_text}\n\n{status}: {operator}"


# Всплывающие окна у оператора после нажатия кнопки
CLIENT_BLOCKED = "Клиент заблокировал бота, ответ не доставлен."
REPLY_SEND_UNCONFIRMED = "Отправка не подтверждена. Проверьте доставку."
CARD_TOO_OLD = "Карточка слишком старая, бот не может ее изменить."
CARD_OUTDATED = "Карточка устарела: ее кнопки больше не поддерживаются."
TICKET_UNAVAILABLE = "Не удалось получить обращение. Попробуйте позже."
TICKET_NOT_FOUND = "Обращение не найдено. Ответ не отправлен."
REPLY_SAVE_FAILED = "Ответ доставлен, но не сохранен в истории. Не отправляйте его повторно."
CARD_UPDATE_FAILED = "Карточку не удалось обновить. Ответ уже доставлен, не отправляйте его повторно."
EDIT_NOT_READY = "Исправление черновика скоро будет."
NOT_OPERATOR = "Отвечать на заявки могут только операторы."


# --- Команда /status ---

# Статусы из базы – так их видит клиент. Значения ставит worker
STATUS_NAMES = {
    "new": "Новое",
    "processing": "В обработке",
    "classified": "Разобрано",
    "failed": "Передано оператору",
}

# База хранит время в UTC, клиенту показываем московское
TIMEZONE = ZoneInfo("Europe/Moscow")

NO_TICKETS = "У вас пока нет обращений. Напишите свой вопрос одним сообщением."
STATUS_UNAVAILABLE = "Не удалось получить список обращений. Попробуйте позже."


def status_list(tickets: list[tuple[int, str, datetime]]) -> Text:
    """Ответ на /status: карточка на каждое обращение с номером, временем и статусом."""
    if not tickets:
        return Text(NO_TICKETS)
    parts = ["Ваши последние обращения:"]
    for ticket_id, status, created_at in tickets:
        local = created_at.astimezone(TIMEZONE)
        # Незнакомый статус показываем как есть, а не падаем
        name = STATUS_NAMES.get(status, status)
        # Bold – жирный шрифт только для номера, остальное обычным текстом
        parts += ["\n\n", Bold(f"Обращение #{ticket_id}"), f"\n{local:%d.%m.%y, %H:%M}\nСтатус: {name}"]
    return Text(*parts)


def chat_ids(chat_id: int, thread_id: int | None) -> str:
    """Ответ на /chat_id — номера группы и темы для .env."""
    return f"OPERATOR_CHAT_ID={chat_id}\nOPERATOR_THREAD_ID={thread_id or ''}"


# Описания команд в меню бота (кнопка «Меню» рядом с полем ввода)
COMMAND_START = "Начать"
COMMAND_HELP = "Как пользоваться ботом"
COMMAND_STATUS = "Мои обращения"
