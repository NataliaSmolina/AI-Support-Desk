"""Тексты сообщений бота."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.utils.formatting import Bold, Italic, Text

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

BUTTON_REPLY = "Ответить"
OPERATOR_REQUESTED = "Передали ваш вопрос оператору."
OPERATOR_HANDOFF_FAILED = "Вопрос сохранен. Передача оператору не подтверждена."


def card(question: str, ticket_id: int, *, requested_operator: bool = False, reason: str | None = None) -> str:
    if not reason:
        reason = "Клиент попросил оператора" if requested_operator else "Требуется ответ оператора"
    return f"Обращение #{ticket_id}\n{reason}\n\nВопрос клиента:\n{question[:1800]}"


# Всплывающие окна у оператора после нажатия кнопки
CLIENT_BLOCKED = "Не удалось отправить ответ. Код: 101"
REPLY_SEND_UNCONFIRMED = "Отправка не подтверждена. Код: 102"
CARD_OUTDATED = "Карточка устарела: ее кнопки больше не поддерживаются."
TICKET_UNAVAILABLE = "Не удалось получить обращение. Попробуйте позже."
TICKET_NOT_FOUND = "Обращение не найдено. Ответ не отправлен."
REPLY_SAVE_FAILED = "Ответ отправлен, но не сохранен в истории. Код: 204"
CARD_UPDATE_FAILED = "Ответ отправлен, карточка не обновлена. Код: 103"
NOT_OPERATOR = "Отвечать на заявки могут только операторы."
TICKET_USAGE = "Укажите номер обращения: /ticket №"
REPLY_PROMPT_PREFIX = "Напишите ответ на обращение #"
REPLY_LINK_INVALID = "Неверная ссылка на обращение."
REPLY_OPEN_FROM_CARD = "Снова нажмите «Ответить» на карточке обращения в группе."
REPLY_ALREADY_OPEN = "Сначала отправьте текущий ответ или отмените его через /cancel."
REPLY_NOT_OPEN = "Нет активного ответа. Откройте обращение из карточки."
REPLY_CANCELLED = "Ответ отменен."
REPLY_USE_PROMPT = "Ответьте на подсказку бота или отправьте /cancel."
REPLY_TEXT_REQUIRED = "Отправьте текст в ответ на подсказку бота."


def worker_result(ticket: dict) -> str:
    """Результат обработки для просмотра оператором."""
    decision = ticket.get("decision")
    if not decision:
        return "Результат обработки еще не готов."

    if decision == "escalate":
        reason = (ticket.get("decision_reason") or "").strip()
        if ticket.get("wants_human") and reason.casefold() == "клиент просит оператора":
            return "Нужен оператор."
        return f"Нужен оператор.\n{reason}" if reason else "Нужен оператор."

    if decision in {"draft", "auto"}:
        title = "Черновик ответа" if decision == "draft" else "Автоматический ответ"
        answer = (ticket.get("answer") or "").strip()
        if not answer:
            return f"{title} отсутствует."
        if len(answer) > 1500:
            answer = answer[:1499].rstrip() + "…"
        return f"{title}:\n{answer}"

    return "Неизвестное решение обработки."


def ticket_details(ticket: dict, messages: list[dict]) -> Text:
    """Карточка для команды /ticket, сообщения могут быть сокращены."""
    human = ticket["wants_human"]
    human_text = "Не определено" if human is None else ("Да" if human else "Нет")
    lines = [
        f"Обращение #{ticket['id']}",
        f"Статус: {ticket['status']}",
        f"Категория: {ticket['category'] or 'Не определена'}",
        f"Приоритет: {ticket['priority'] or 'Не определен'}",
        f"Настроение: {ticket['sentiment'] or 'Не определено'}",
        f"Просьба об операторе: {human_text}",
        f"\nРезультат обработки:\n{worker_result(ticket)}",
        "\nПоследние сообщения:",
    ]
    parts: list[str | Text] = ["\n".join(lines)]
    authors = {"client": Bold("Клиент"), "operator": Italic("Оператор"), "bot": "Бот"}
    for message in messages:
        author = authors.get(message["author"], message["author"])
        parts.extend(("\n", author, f": {message['text']}"))
    if not messages:
        parts.append("\nСообщений пока нет")
    return Text(*parts)


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
        # Внутреннее значение неизвестного статуса клиенту не показываем
        name = STATUS_NAMES.get(status, "Уточняется")
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
