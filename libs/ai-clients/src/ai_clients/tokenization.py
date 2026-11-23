"""Подсчёт токенов без запуска моделей и без обрезки текста.

Перед первым использованием: python -m ai_clients.tokenization --download.
Скачиваются только токенизаторы. Клиенты сначала используют локальный кеш;
при отсутствии файлов разрешено скачивание, если TOKENIZER_LOCAL_FILES_ONLY=false.
Для работы без сети предварительно скачайте файлы и задайте true. Без --download
эта CLI проверяет только кеш. Можно задать путь к локальному токенизатору
через TEI_TOKENIZER / LLM_TOKENIZER. При смене модели нужен её токенизатор.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol

from .config import ModelInputLimits


class InputTooLongError(ValueError):
    """Вход не помещается: это не отсутствие знаний и не сбой сервера модели."""

    def __init__(self, message: str, *, tokens: int, limit: int):
        super().__init__(message)
        self.tokens = tokens
        self.limit = limit


class TokenizationError(RuntimeError):
    """Токенизатор недоступен или не поддерживает формат сообщений."""


class TokenCounter(Protocol):
    def count_text(self, text: str) -> int: ...
    def count_messages(self, messages: list[dict[str, str]], *, schema: dict | None = None) -> int: ...


TOKENIZER_FILES = [
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
    "chat_template.jinja", "vocab.json", "merges.txt", "config.json",
    "sentencepiece.bpe.model", "spiece.model", "tokenizer.model",
]


def _tokenizer_directory(source: str, revision: str, *, local_files_only: bool) -> str:
    if Path(source).is_dir():
        return source
    from huggingface_hub import snapshot_download
    return snapshot_download(
        source, revision=revision, local_files_only=local_files_only,
        allow_patterns=TOKENIZER_FILES,
    )


class _TokenizerHandle:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        # HF fast tokenizer изменяет настройки truncation/padding при encode.
        # Один кешированный экземпляр может использоваться несколькими клиентами.
        self.lock = Lock()


@lru_cache(maxsize=4)
def _load_tokenizer(source: str, revision: str, local_files_only: bool):
    from transformers import AutoTokenizer

    try:
        directory = _tokenizer_directory(source, revision, local_files_only=True)
        tokenizer = AutoTokenizer.from_pretrained(
            directory, use_fast=True, trust_remote_code=False,
            local_files_only=True,
        )
    except OSError:
        if local_files_only:
            raise
        directory = _tokenizer_directory(source, revision, local_files_only=False)
        tokenizer = AutoTokenizer.from_pretrained(
            directory, use_fast=True, trust_remote_code=False, local_files_only=True,
        )
    return _TokenizerHandle(tokenizer)


class ModelTokenizer:
    def __init__(self, source: str, revision: str, *, local_files_only: bool = True):
        self.source = source
        self.revision = revision
        self.local_files_only = local_files_only

    def _get(self):
        try:
            return _load_tokenizer(self.source, self.revision, self.local_files_only)
        except Exception as exc:
            raise TokenizationError(
                "Токенизатор не загружен. Выполните: "
                "uv run python -m ai_clients.tokenization --download"
            ) from exc

    def count_text(self, text: str) -> int:
        try:
            loaded = self._get()
            with loaded.lock:
                return len(loaded.tokenizer.encode(
                    text, add_special_tokens=True, truncation=False, verbose=False,
                ))
        except TokenizationError:
            raise
        except Exception as exc:
            raise TokenizationError("Не удалось посчитать токены текста") from exc

    def count_messages(self, messages: list[dict[str, str]], *, schema: dict | None = None) -> int:
        try:
            loaded = self._get()
            with loaded.lock:
                tokenizer = loaded.tokenizer
                # Роли, разделители и начало ответа; как в наших запросах think=False.
                # Пустой список используется Ollama для загрузки модели без prompt.
                prompt = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
                ) if messages else ""
                count = len(tokenizer.encode(
                    prompt, add_special_tokens=False, truncation=False, verbose=False,
                ))
                # OpenAI-совместимый сервер может добавлять схему в prompt.
                if schema is not None:
                    count += len(tokenizer.encode(
                        json.dumps(schema, ensure_ascii=False), add_special_tokens=False,
                        truncation=False, verbose=False,
                    ))
                return count
        except TokenizationError:
            raise
        except Exception as exc:
            raise TokenizationError("Не удалось посчитать токены сообщений: проверьте chat template") from exc


@dataclass(frozen=True)
class ContextUsage:
    input_tokens: int
    output_tokens: int
    reserve_tokens: int
    context_tokens: int

    @property
    def input_limit(self) -> int:
        return self.context_tokens - self.output_tokens - self.reserve_tokens

    @property
    def fits(self) -> bool:
        return self.input_tokens <= self.input_limit

    def ensure_fits(self) -> None:
        if not self.fits:
            raise InputTooLongError(
                f"LLM: вход содержит {self.input_tokens} токенов, доступно {self.input_limit}; "
                f"контекст {self.context_tokens}, резерв ответа {self.output_tokens}, "
                f"запас {self.reserve_tokens}. Сократите входной текст.",
                tokens=self.input_tokens, limit=self.input_limit,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Скачать только файлы токенизаторов в кеш HF")
    args = parser.parse_args()
    limits = ModelInputLimits()
    for name, source, revision in (
        ("TEI", limits.tei_tokenizer, limits.tei_tokenizer_revision),
        ("LLM", limits.llm_tokenizer, limits.llm_tokenizer_revision),
    ):
        try:
            if args.download:
                _tokenizer_directory(source, revision, local_files_only=False)
            counter = ModelTokenizer(source, revision)
            tokens = (counter.count_text("Проверка токенизатора") if name == "TEI" else
                      counter.count_messages([{"role": "user", "content": "Проверка токенизатора"}]))
        except (TokenizationError, OSError, ValueError) as exc:
            print(f"{name}: токенизатор недоступен ({type(exc).__name__}). "
                  "Проверьте пути и доступ к Hugging Face; для загрузки используйте --download.", file=sys.stderr)
            return 1
        print(f"{name}: {source}, revision={revision}; проверка: {tokens} токенов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
