from support_bot import texts
from support_bot.keyboards import DraftAction, draft_keyboard


def test_draft_keyboard_has_two_buttons():
    keyboard = draft_keyboard(chat_id=111)

    buttons = keyboard.inline_keyboard[0]

    assert [b.text for b in buttons] == [texts.BUTTON_SEND, texts.BUTTON_EDIT]


def test_button_keeps_client_chat_id():
    keyboard = draft_keyboard(chat_id=111)
    send_button = keyboard.inline_keyboard[0][0]

    # Строку из кнопки превращаем обратно в объект
    data = DraftAction.unpack(send_button.callback_data)

    assert data.action == "send"
    assert data.chat_id == 111
