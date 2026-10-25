import hashlib
from dataclasses import dataclass


def _stable_hash(*parts: str) -> str:
    """Считает SHA-256 по частям через NUL-разделитель.

    NUL не может встретиться в тексте Markdown/заголовках, поэтому разные
    комбинации частей не склеиваются в одинаковую строку.
    """
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Document:
    """Represents a raw markdown document loaded from the file system."""
    source_file: str
    content: str

    @property
    def doc_hash(self) -> str:
        """Hash of the whole document including its source path."""
        return _stable_hash(self.source_file, self.content)


@dataclass(frozen=True)
class Chunk:
    """Represents a semantic chunk of a document."""
    text: str
    headers: tuple[str, ...] = ()
    source_file: str = ""

    @property
    def content_hash(self) -> str:
        """
        Hash of the chunk identity: source file, text and header hierarchy.
        It is derived from the chunk fields, so it cannot get out of sync
        with them and is safe to use as the UPSERT key.
        """
        return _stable_hash(self.source_file, self.text, *self.headers)
