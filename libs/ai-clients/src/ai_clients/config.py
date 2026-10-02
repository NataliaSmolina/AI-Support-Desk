from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    """Адреса и параметры сервисов моделей. Читаются из переменных окружения или .env.

    С компьютера разработчика — порты из infra/*/compose.yml (127.0.0.1:8081).
    Из контейнера внутри Docker — имена сервисов (http://tei:80).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tei_embed_url: str = "http://127.0.0.1:8081"
    request_timeout_s: float = 180.0
