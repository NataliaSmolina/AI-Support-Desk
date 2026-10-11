from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kb_dir: str = "./kb"
    tei_url: str = "http://127.0.0.1:8081"
    embed_batch_size: int = 32

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_user: str = "supportdesk"
    postgres_password: str = "supportdesk"
    postgres_db: str = "supportdesk"

    embedding_dimension: int = 384

    @computed_field
    @property
    def database_url(self) -> str:
        """Собирает строку подключения из отдельных переменных окружения."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()