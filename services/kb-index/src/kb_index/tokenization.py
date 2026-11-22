import hashlib
from pathlib import Path
from typing import Protocol

from tokenizers import Tokenizer


class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        """Возвращает число токенов в тексте."""


class HfTokenizerCounter:
    """Считает токены через локальный tokenizer.json."""

    def __init__(self, tokenizer_path: str | Path):
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=True).ids)


def find_tokenizer_path(
    model_id: str,
    cache_dir: str | Path | None = None,
) -> Path:
    """Находит tokenizer.json в кэше Hugging Face или в volume TEI."""
    cache_name = "models--" + model_id.replace("/", "--")
    roots = (
        [Path(cache_dir)]
        if cache_dir
        else [Path("/tei-models"), Path.home() / ".cache" / "huggingface"]
    )

    candidates: list[Path] = []
    for root in roots:
        snapshots = root / cache_name / "snapshots"
        if snapshots.is_dir():
            candidates.extend(snapshots.glob("*/tokenizer.json"))

    if not candidates:
        searched = ", ".join(str(root / cache_name) for root in roots)
        raise FileNotFoundError(
            f"tokenizer.json для модели {model_id!r} не найден. "
            f"Проверены пути: {searched}"
        )

    return max(candidates, key=lambda path: path.stat().st_mtime)


def sha256_file(path: str | Path) -> str:
    """Считает SHA-256 файла, например tokenizer.json."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
