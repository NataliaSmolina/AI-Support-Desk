import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    dsn: str
    max_attempts: int = 3
    lock_timeout_s: float = 300   # тикет дольше этого считается брошенным
    heartbeat_s: float = 60       # как часто живой worker подтверждает, что работает
    poll_s: float = 2             # пауза, если очередь пуста
    recover_s: float = 30         # как часто искать зависшие тикеты
    backoff_base_s: float = 5     # задержка перед повтором:
    backoff_cap_s: float = 300

    def __post_init__(self) -> None:
        if self.heartbeat_s * 3 > self.lock_timeout_s:
            raise ValueError("heartbeat_s * 3 должно быть не больше lock_timeout_s")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("Не задана переменная DATABASE_URL")
        env = os.getenv
        return cls(
            dsn=dsn,
            max_attempts=int(env("WORKER_MAX_ATTEMPTS", "3")),
            lock_timeout_s=float(env("WORKER_LOCK_TIMEOUT_S", "300")),
            heartbeat_s=float(env("WORKER_HEARTBEAT_S", "60")),
            poll_s=float(env("WORKER_POLL_S", "2")),
            recover_s=float(env("WORKER_RECOVER_S", "30")),
            backoff_base_s=float(env("WORKER_BACKOFF_BASE_S", "5")),
        )