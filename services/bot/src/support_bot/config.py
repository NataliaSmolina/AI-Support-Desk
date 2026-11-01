from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Настройки бота из файла .env."""

    # env_ignore_empty: пустая строка в .env (например, OPERATOR_THREAD_ID=) считается «не задано»
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # SecretStr прячет токен при печати: вместо него выводится '**********'
    bot_token: SecretStr = Field(min_length=1)

    # Группа операторов, куда бот шлёт карточки.
    operator_chat_id: int | None = None
    # Для бота в группе
    operator_thread_id: int | None = None

    # Операторы бота по id
    operator_ids: list[int] = []

    # Адрес базы
    database_url: SecretStr | None = None
