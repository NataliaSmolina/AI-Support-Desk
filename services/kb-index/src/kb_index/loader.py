from pathlib import Path
from typing import Protocol

from .models import Document


class Loader(Protocol):
    def source(self) -> str:
        """Возвращает человекочитаемое описание источника документов."""

    def load(self) -> list[Document]:
        """Загружает документы из источника."""


class LocalDirectoryLoader:
    def __init__(self, directory: str):
        self._directory = Path(directory)
        if not self._directory.exists() or not self._directory.is_dir():
            raise ValueError(f"Directory not found: {directory}")

    def source(self) -> str:
        return str(self._directory)

    def load(self) -> list[Document]:
        """Читает kb/*.md (Блок 1 схемы)"""
        documents = []
        for file_path in self._directory.rglob("*.md"):
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                documents.append(Document(source_file=str(file_path), content=content))
        return documents
