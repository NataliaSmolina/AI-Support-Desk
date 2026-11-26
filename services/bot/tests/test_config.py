import pytest
from pydantic import ValidationError

from support_bot.config import BotSettings


def test_empty_token_is_error(monkeypatch):
    # Пустой BOT_TOKEN не позволяет создать настройки и запустить бота
    monkeypatch.setenv("BOT_TOKEN", "")

    with pytest.raises(ValidationError):
        BotSettings(_env_file=None)


def test_token_is_hidden_when_printed(monkeypatch):
    # При печати настроек токен скрыт. Для подключения бот может получить его полное значение
    monkeypatch.setenv("BOT_TOKEN", "123:secret")

    settings = BotSettings(_env_file=None)

    assert "secret" not in str(settings)
    assert settings.bot_token.get_secret_value() == "123:secret"


def test_operator_group_is_optional(monkeypatch):
    # Без ID группы и с пустым ID темы настройки загружаются, оба значения равны None
    monkeypatch.setenv("BOT_TOKEN", "123:secret")
    monkeypatch.setenv("OPERATOR_THREAD_ID", "")

    settings = BotSettings(_env_file=None)

    assert settings.operator_chat_id is None
    assert settings.operator_thread_id is None
