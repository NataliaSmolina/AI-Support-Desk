from abc import ABC, abstractmethod
from pathlib import Path

from .models import Document


class Loader(ABC):
    @abstractmethod
    def load(self) -> list[Document]:
        """Загружает документы из источника."""


class LocalDirectoryLoader(Loader):
    def __init__(self, directory: str):
        self.directory = Path(directory)
        if not self.directory.exists() or not self.directory.is_dir():
            raise ValueError(f"Directory not found: {directory}")

    def load(self) -> list[Document]:
        """Читает kb/*.md (Блок 1 схемы)"""
        documents = []
        for file_path in self.directory.rglob("*.md"):
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                documents.append(Document(source_file=str(file_path), content=content))
        return documents