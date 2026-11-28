from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage
from aiogram.types import Update

from support_bot import db, texts
from support_bot.handlers.operator import GROUP_CHAT, chat_id, router, ticket_command
from support_bot.handlers.reply import OperatorReply, ReplyCard, pending_cards, router as reply_router, send_reply, start_reply


async def test_chat_id_shows_group_and_topic():
    # /chat_id возвращает ID группы и темы в формате строк для .env
    message = AsyncMock()
    message.chat.id = -100222
    message.message_thread_id = 5

    await chat_id(message)

    message.answer.assert_awaited_once_with("OPERATOR_CHAT_ID=-100222\nOPERATOR_THREAD_ID=5")


def test_operator_handlers_only_in_groups():
    # Фильтр группового роутера принимает супергруппу и исключает личный чат
    group = SimpleNamespace(chat=SimpleNamespace(type="supergroup"))
    private = SimpleNamespace(chat=SimpleNamespace(type="private"))

    assert GROUP_CHAT.resolve(group) is True
    assert GROUP_CHAT.resolve(private) is False


def reply_context(user_id=123, prompt_id=42):
    message = AsyncMock()
    message.text = "Ваш заказ уже в пути."
    message.from_user.id = user_id
    message.reply_to_message.message_id = prompt_id
    state = AsyncMock()
    message.from_user.full_name = "Иван Петров"
    state.get_data.return_value = {
        "ticket_id": 15, "reply_round": 1, "prompt_id": 42, "card": ReplyCard(15, -100222, 77, "Обращение #15"),
    }
    state.get_state.return_value = OperatorReply.waiting_for_text.state
    return message, state, SimpleNamespace(operator_ids=[123])


@pytest.mark.parametrize(("saved", "save_error"), [
    # История сохранена – оператор получает подтверждение отправки
    (True, None),
    # База выполнила запрос, но не приняла подтверждение для текущего раунда
    (False, None),
    # История не сохранилась – после отправки бот предупреждает об этом оператора
    (False, psycopg.OperationalError("database unavailable")),
])
async def test_send_uses_chat_from_ticket(monkeypatch, saved, save_error):
    # Бот берет адресата из тикета, отправляет ответ, завершает ввод и обновляет карточку именем оператора
    lookup = AsyncMock(return_value=db.OperatorTicket(111, 1, "operator_processing", 123))
    monkeypatch.setattr(db, "operator_ticket", lookup)
    confirm_reply = AsyncMock(return_value=saved, side_effect=save_error)
    monkeypatch.setattr(db, "confirm_operator_reply", confirm_reply)
    message, state, settings = reply_context()
    bot = AsyncMock()
    pool = object()

    await send_reply(message, bot, state, settings, pool)

    lookup.assert_awaited_once_with(pool, 15)
    bot.send_message.assert_awaited_once_with(chat_id=111, text=message.text)
    confirm_reply.assert_awaited_once_with(pool, 15, 1, 123, message.text)
    state.clear.assert_awaited_once()
    card_text = "Обращение #15\n\nОбработал: Иван Петров"
    if not saved:
        card_text += "\nОтвет отправлен, история не сохранена."
    bot.edit_message_text.assert_awaited_once_with(chat_id=-100222, message_id=77, text=card_text)
    expected = "Ответ на обращение #15 отправлен." if saved else texts.REPLY_SAVE_FAILED
    message.answer.assert_awaited_once_with(expected)


async def test_send_does_not_save_unconfirmed_reply(monkeypatch):
    # При таймауте бот завершает ввод и сообщает, что отправка не подтверждена. История и карточка не обновляются
    monkeypatch.setattr(db, "operator_ticket", AsyncMock(return_value=db.OperatorTicket(111, 1, "operator_processing", 123)))
    confirm_reply = AsyncMock()
    monkeypatch.setattr(db, "confirm_operator_reply", confirm_reply)
    message, state, settings = reply_context()
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramNetworkError(
        method=SendMessage(chat_id=111, text=message.text), message="timeout",
    )

    await send_reply(message, bot, state, settings, object())

    confirm_reply.assert_not_awaited()
    bot.edit_message_text.assert_not_awaited()
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once_with(texts.REPLY_SEND_UNCONFIRMED)


@pytest.mark.parametrize(
    "with_pool, result, error, expected",
    [
        # Без пула бот сразу сообщает, что обращение недоступно
        (False, None, None, texts.TICKET_UNAVAILABLE),
        # Поиск не вернул чат клиента – обращение не найдено
        (True, None, None, texts.TICKET_NOT_FOUND),
        # Ошибка запроса к базе – обращение временно недоступно
        (True, None, psycopg.OperationalError, texts.TICKET_UNAVAILABLE),
    ],
)
async def test_send_does_not_deliver_when_ticket_unavailable(monkeypatch, with_pool, result, error, expected):
    # Во всех трех случаях оператору приходит объяснение, отправка клиенту не вызывается
    lookup = AsyncMock(return_value=result, side_effect=error)
    monkeypatch.setattr(db, "operator_ticket", lookup)
    message, state, settings = reply_context()
    bot = AsyncMock()

    await send_reply(message, bot, state, settings, pool=object() if with_pool else None)

    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once_with(expected)
    if not with_pool:
        lookup.assert_not_awaited()


@pytest.mark.parametrize("ticket", [
    db.OperatorTicket(111, 1, "operator_processing", 999),  # Тикет назначен другому оператору
    db.OperatorTicket(111, 2, "operator_processing", 123),  # Подсказка относится к прошлому раунду
    db.OperatorTicket(111, 1, "waiting_client", 123),  # Клиенту уже ответили
])
async def test_send_rechecks_assignment_and_round(monkeypatch, ticket):
    # Если назначение, раунд или этап изменились, отменяем старый ввод до отправки
    monkeypatch.setattr(db, "operator_ticket", AsyncMock(return_value=ticket))
    message, state, settings = reply_context()
    bot = AsyncMock()

    await send_reply(message, bot, state, settings, object())

    bot.send_message.assert_not_awaited()
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once_with(texts.REPLY_TICKET_INACTIVE)


@pytest.mark.parametrize(
    "user_id, prompt_id, expected",
    [
        # Подсказка правильная, но автор сообщения отсутствует в списке операторов
        (999, 42, texts.NOT_OPERATOR),
        # Оператор авторизован, но отвечает на старую подсказку
        (123, 41, texts.REPLY_USE_PROMPT),
    ],
)
async def test_reply_requires_operator_and_current_prompt(monkeypatch, user_id, prompt_id, expected):
    # Проверки доступа и подсказки отклоняют ответ до поиска клиента в БД и отправки
    lookup = AsyncMock()
    monkeypatch.setattr(db, "operator_ticket", lookup)
    message, state, settings = reply_context(user_id, prompt_id)
    bot = AsyncMock()

    await send_reply(message, bot, state, settings, object())

    lookup.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once_with(expected)


@pytest.mark.parametrize("data", [
    # Старый формат кнопки содержал ID чата клиента
    "draft:send:111",
    # Промежуточный формат кнопки содержал номер обращения
    "ticket_draft:send:15",
])
async def test_old_button_is_rejected_by_router(data):
    # Любая устаревшая кнопка показывает предупреждение через роутер
    callback = AsyncMock()
    callback.data = data
    await router.callback_query.trigger(callback)

    callback.answer.assert_awaited_once_with(texts.CARD_OUTDATED, show_alert=True)


async def test_reply_link_and_cancel_through_dispatcher(monkeypatch):
    # Проверяем весь переход от кнопки в группе до отмены ответа в личке через Dispatcher
    bot = AsyncMock()
    bot.id = 44
    bot.return_value = SimpleNamespace(message_id=42)
    bot.me.return_value.username = "support_bot"
    pool = object()
    claim = AsyncMock(return_value=db.OperatorTicket(111, 1, "operator_processing", 123))
    monkeypatch.setattr(db, "claim_operator_ticket", claim)
    dispatcher = Dispatcher(settings=SimpleNamespace(operator_ids=[123], operator_chat_id=-100222), pool=pool)
    dispatcher.include_router(reply_router)

    async def send_command(update_id, user_id, text):
        update = Update.model_validate({
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
                "text": text,
            },
        })
        await dispatcher.feed_update(bot, update)

    try:
        # Кнопка тикета №15 возвращает ссылку для перехода в личный чат
        await dispatcher.feed_update(bot, Update.model_validate({
            "update_id": 10,
            "callback_query": {
                "id": "reply-click",
                "from": {"id": 123, "is_bot": False, "first_name": "Иван"},
                "chat_instance": "group",
                "data": "reply:15",
                "message": {
                    "message_id": 77,
                    "date": 1,
                    "chat": {"id": -100222, "type": "supergroup"},
                    "text": "Обращение #15\nВопрос клиента",
                },
            },
        }))
        assert bot.await_args.args[0].url == "https://t.me/support_bot?start=reply_15"

        # Переход по ссылке запоминает номер тикета, подсказку и исходную карточку
        await send_command(1, 123, "/start reply_15")
        claim.assert_awaited_once_with(pool, 15, 123)
        state = dispatcher.fsm.get_context(bot=bot, chat_id=123, user_id=123)
        assert await state.get_data() == {
            "ticket_id": 15, "reply_round": 1, "prompt_id": 42,
            "card": ReplyCard(15, -100222, 77, "Обращение #15\nВопрос клиента"),
        }

        # Пользователь вне списка операторов не может открыть ответ по ссылке
        await send_command(2, 999, "/start reply_15")
        assert bot.await_args.args[0].text == texts.NOT_OPERATOR

        # Второе обращение не подменяет текущий тикет, пока оператор пишет ответ
        await send_command(3, 123, "/start reply_16")
        assert bot.await_args.args[0].text == texts.REPLY_ALREADY_OPEN
        assert (await state.get_data())["ticket_id"] == 15

        # /cancel прекращает ввод и очищает данные текущего ответа
        await send_command(4, 123, "/cancel")
        assert bot.await_args.args[0].text == texts.REPLY_CANCELLED
        assert await state.get_state() is None
        assert await state.get_data() == {}
    finally:
        reply_router._parent_router = None


async def test_start_reply_refuses_ticket_already_taken(monkeypatch):
    # Оператор из списка не получает подсказку, если тикет уже назначен коллеге
    bot = SimpleNamespace(id=44)
    message = AsyncMock()
    message.from_user.id = 999
    state = AsyncMock()
    state.get_state.return_value = None
    settings = SimpleNamespace(operator_ids=[123, 999])
    monkeypatch.setitem(pending_cards, (bot.id, 999), ReplyCard(15, -100222, 77, "Обращение #15"))
    monkeypatch.setattr(db, "claim_operator_ticket", AsyncMock(
        return_value=db.OperatorTicket(111, 1, "operator_processing", 123),
    ))

    await start_reply(message, CommandObject(args="reply_15"), state, settings, bot, object())

    message.answer.assert_awaited_once_with(texts.REPLY_TICKET_TAKEN)
    state.set_state.assert_not_awaited()


@pytest.mark.parametrize("chat_id, user_id", [
    # Правильная группа, но автор не оператор
    (-100222, 999),
    # Оператор авторизован, но команда отправлена в другой группе
    (-100333, 123),
    # Не совпадают ни группа, ни оператор
    (-100333, 999),
])
async def test_ticket_command_denies_wrong_user_or_group(monkeypatch, chat_id, user_id):
    # При отказе в доступе /ticket не читает обращение и ничего не пишет в чат
    lookup = AsyncMock()
    monkeypatch.setattr(db, "ticket_details", lookup)
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = user_id
    settings = SimpleNamespace(operator_chat_id=-100222, operator_ids=[123])

    await ticket_command(message, CommandObject(args="15"), settings, pool=object())

    lookup.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.parametrize("configured_chat, user_id, operators", [
    # Группа операторов не настроена
    (None, 123, [123]),
    # Список допущенных операторов пуст
    (-100222, 123, []),
    # У сообщения отсутствует автор, проверять доступ не по кому
    (-100222, None, [123]),
])
async def test_ticket_command_denies_missing_access_settings(monkeypatch, configured_chat, user_id, operators):
    # При неполных данных для проверки доступа команда не читает и не показывает тикет
    lookup = AsyncMock()
    monkeypatch.setattr(db, "ticket_details", lookup)
    message = AsyncMock()
    message.chat.id = -100222
    message.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
    settings = SimpleNamespace(operator_chat_id=configured_chat, operator_ids=operators)

    await ticket_command(message, CommandObject(args="15"), settings, pool=object())

    lookup.assert_not_awaited()
    message.answer.assert_not_awaited()


@pytest.mark.parametrize("args", [
    None,  # Аргумент отсутствует
    "",  # Аргумент есть, но он пустой
    "abc",  # Вместо номера введены буквы
    "0",  # Номер должен быть больше нуля
    "-1",  # Отрицательный номер недопустим
    "15 16",  # Команда принимает один номер
    "9223372036854775808",  # Число на единицу больше максимума BIGINT
    "9" * 100,  # Ввод сильно длиннее допустимых 19 цифр
])
async def test_ticket_command_rejects_invalid_number(monkeypatch, args):
    # При неверном номере бот показывает подсказку, запрос к базе не выполняется
    lookup = AsyncMock()
    monkeypatch.setattr(db, "ticket_details", lookup)
    message = AsyncMock()
    message.chat.id = -100222
    message.from_user.id = 123
    settings = SimpleNamespace(operator_chat_id=-100222, operator_ids=[123])

    await ticket_command(message, CommandObject(args=args), settings, pool=object())

    lookup.assert_not_awaited()
    message.answer.assert_awaited_once_with(texts.TICKET_USAGE)


async def test_ticket_command_shows_classification_and_messages(monkeypatch):
    # /ticket показывает категорию, просьбу об операторе и историю с оформлением подписей авторов
    ticket = {"id": 15, "status": "classified", "category": "delivery", "priority": "normal",
              "sentiment": "calm", "wants_human": False}
    messages = [
        {"author": "client", "text": "📦 Где заказ?"},
        {"author": "operator", "text": "Заказ в пути."},
    ]
    lookup = AsyncMock(return_value=(ticket, messages))
    monkeypatch.setattr(db, "ticket_details", lookup)
    message = AsyncMock()
    message.chat.id = -100222
    message.from_user.id = 123
    settings = SimpleNamespace(operator_chat_id=-100222, operator_ids=[123])
    pool = object()

    await ticket_command(message, CommandObject(args="15"), settings, pool=pool)

    lookup.assert_awaited_once_with(pool, 15)
    sent = message.answer.await_args.kwargs
    answer = sent["text"]
    assert "Обращение #15" in answer
    assert "Категория: delivery" in answer
    assert "Просьба об операторе: Нет" in answer
    assert "Клиент: 📦 Где заказ?\nОператор: Заказ в пути." in answer
    assert [(entity.type, entity.extract_from(answer)) for entity in sent["entities"]] == [
        ("bold", "Клиент"),
        ("italic", "Оператор"),
    ]


@pytest.mark.parametrize("error, result, expected", [
    # Запрос упал – бот сообщает оператору, что обращение недоступно
    (psycopg.OperationalError("unavailable"), None, texts.TICKET_UNAVAILABLE),
    # Запрос выполнен, но запись отсутствует – бот сообщает, что обращение не найдено
    (None, None, texts.TICKET_NOT_FOUND),
])
async def test_ticket_command_handles_database_errors(monkeypatch, error, result, expected):
    # Для ошибки базы и отсутствующего тикета оператор получает разные сообщения
    monkeypatch.setattr(db, "ticket_details", AsyncMock(side_effect=error, return_value=result))
    message = AsyncMock()
    message.chat.id = -100222
    message.from_user.id = 123
    settings = SimpleNamespace(operator_chat_id=-100222, operator_ids=[123])

    await ticket_command(message, CommandObject(args="15"), settings, pool=object())

    message.answer.assert_awaited_once_with(expected)


async def test_ticket_command_without_database(monkeypatch):
    # Без пула /ticket отвечает, что обращение недоступно, и не вызывает запрос к БД
    lookup = AsyncMock()
    monkeypatch.setattr(db, "ticket_details", lookup)
    message = AsyncMock()
    message.chat.id = -100222
    message.from_user.id = 123
    settings = SimpleNamespace(operator_chat_id=-100222, operator_ids=[123])

    await ticket_command(message, CommandObject(args="15"), settings)

    lookup.assert_not_awaited()
    message.answer.assert_awaited_once_with(texts.TICKET_UNAVAILABLE)


def test_ticket_details_shows_unclassified_fields():
    # Для нового тикета видны подсказки о пустых полях и истории, оформление авторов отсутствует
    ticket = {"id": 15, "status": "new", "category": None, "priority": None,
              "sentiment": None, "wants_human": None}
    answer, entities = texts.ticket_details(ticket, []).render()

    assert "Категория: Не определена" in answer
    assert "Просьба об операторе: Не определено" in answer
    assert "Сообщений пока нет" in answer
    assert not entities
