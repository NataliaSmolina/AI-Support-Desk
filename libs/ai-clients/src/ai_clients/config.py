from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    """Адреса и параметры сервисов моделей. Читаются из переменных окружения или .env.

    С компьютера разработчика — порты из infra/*/compose.yml (127.0.0.1:8081).
    Из контейнера внутри Docker — имена сервисов (http://tei:80).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tei_embed_url: str = "http://127.0.0.1:8081"
    llm_provider: Literal["ollama", "openai"] = "ollama"
    llm_health_timeout_s: float = Field(default=5.0, gt=0)
    llm_base_url: str = "http://127.0.0.1:11500/v1"
    llm_model: str = "qwen3:8b"
    request_timeout_s: float = 180.0


class RagSettings(BaseSettings):
    """Поиск читает ту же БД, что и Worker. Порог требует отдельной калибровки."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    embedding_dimension: int = Field(default=1024, ge=1)
    rag_top_k: int = Field(default=5, ge=1, le=100)
    rag_max_distance: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    rag_search_timeout_s: float = Field(default=10, gt=0, allow_inf_nan=False)
