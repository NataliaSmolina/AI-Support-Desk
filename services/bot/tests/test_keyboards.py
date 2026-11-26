from support_bot.keyboards import reply_keyboard


def test_reply_button_carries_ticket_number():
    # В карточке одна кнопка «Ответить», а ее callback передает номер нужного обращения
    keyboard = reply_keyboard(ticket_id=15)

    (row,) = keyboard.inline_keyboard
    (button,) = row
    assert button.text == "Ответить"
    assert button.callback_data == "reply:15"
