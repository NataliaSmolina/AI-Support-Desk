from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки сервиса kb-index.

    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    kb_dir: str = "./kb"

    embed_batch_size: int = Field(default=32, ge=1)

    embedding_dimension: int = Field(default=1024, ge=1)

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5433, ge=1, le=65535)
    postgres_user: str = "supportdesk"
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = "supportdesk"

    @computed_field
    @property
    def database_url(self) -> str:
        """Собирает строку подключения из отдельных переменных окружения."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Ленивая инициализация настроек.
    
    """
    return Settings()