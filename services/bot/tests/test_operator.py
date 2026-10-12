from types import SimpleNamespace
from unittest.mock import AsyncMock

from support_bot.handlers.operator import GROUP_CHAT, chat_id


async def test_chat_id_shows_group_and_topic():
    message = AsyncMock()
    message.chat.id = -100222
    message.message_thread_id = 5

    await chat_id(message)

    message.answer.assert_awaited_once_with("OPERATOR_CHAT_ID=-100222\nOPERATOR_THREAD_ID=5")


def test_operator_handlers_only_in_groups():
    group = SimpleNamespace(chat=SimpleNamespace(type="supergroup"))
    private = SimpleNamespace(chat=SimpleNamespace(type="private"))

    assert GROUP_CHAT.resolve(group) is True
    assert GROUP_CHAT.resolve(private) is False
