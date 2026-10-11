import pytest
from pydantic import ValidationError

from support_bot.config import BotSettings


def test_empty_token_is_error(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")

    with pytest.raises(ValidationError):
        BotSettings(_env_file=None)


def test_token_is_hidden_when_printed(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:secret")

    settings = BotSettings(_env_file=None)

    assert "secret" not in str(settings)
    assert settings.bot_token.get_secret_value() == "123:secret"
