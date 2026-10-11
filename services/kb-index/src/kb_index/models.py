from dataclasses import dataclass, field
from typing import List
import hashlib

@dataclass
class Document:
    """Represents a raw markdown document loaded from the file system."""
    source_file: str
    content: str
    
    @property
    def doc_hash(self) -> str:
        """Hash of the entire document content to detect global file changes."""
        return hashlib.sha256(self.content.encode('utf-8')).hexdigest()

@dataclass
class Chunk:
    """Represents a semantic chunk of a document."""
    text: str
    headers: List[str] = field(default_factory=list)
    source_file: str = ""
    content_hash: str = ""
    
    def compute_hash(self) -> str:
        """
        Generates a unique hash based on the chunk's text and header hierarchy.
        Used for UPSERT operations to prevent duplicates in the database.
        """
        data = f"{self.text}|{'|'.join(self.headers)}"
        return hashlib.sha256(data.encode('utf-8')).hexdigest()