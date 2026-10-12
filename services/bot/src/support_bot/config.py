from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Настройки бота из файла .env."""

    # env_ignore_empty: пустая строка в .env (например, OPERATOR_THREAD_ID=) считается «не задано»
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # SecretStr прячет токен при печати: вместо него выводится '**********'
    bot_token: SecretStr = Field(min_length=1)

    # Группа операторов, куда бот шлёт карточки. Узнать номера — команда /chat_id в группе.
    # None — группа не задана, карточки не отправляются.
    operator_chat_id: int | None = None
    # Тема (топик) в группе. None — общая тема
    operator_thread_id: int | None = None
