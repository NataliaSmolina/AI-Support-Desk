from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Настройки бота из файла .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr прячет токен при печати: вместо него выводится '**********'
    bot_token: SecretStr = Field(min_length=1)
