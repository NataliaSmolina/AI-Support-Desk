import sys
import random
import logging
from pathlib import Path
from typing import List

from .models import Document, Chunk
from .chunker import chunk_markdown

logger = logging.getLogger(__name__)

def load_documents(directory: str) -> List[Document]:
    """Scans a directory recursively for markdown files and loads their content."""
    documents = []
    path = Path(directory)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory not found: {directory}")
        
    for file_path in path.rglob("*.md"):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        documents.append(Document(
            source_file=str(file_path),
            content=content
        ))
    return documents

def mock_embed(chunks: List[Chunk], dimension: int = 768) -> List[List[float]]:
    """
    Generates random vectors. 
    """
    return [[random.random() for _ in range(dimension)] for _ in chunks]

def mock_upsert(chunks: List[Chunk], embeddings: List[List[float]]) -> None:
    """
    In-memory storage mock. 
    """
    for chunk, emb in zip(chunks, embeddings):
        logger.info(
            "Upserted chunk | source=%s | headers=%s | dim=%d", 
            chunk.source_file, chunk.headers, len(emb)
        )

def run_pipeline(directory: str = "./kb"):
    """Executes the kb-index ETL pipeline."""
    # Configure basic logging format
    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    logger.info("Starting ETL pipeline. Loading documents from: %s", directory)
    docs = load_documents(directory)
    logger.info("Successfully loaded %d documents", len(docs))
    
    total_chunks = 0
    for doc in docs:
        chunks = chunk_markdown(doc)
        if not chunks:
            continue
            
        embeddings = mock_embed(chunks)
        mock_upsert(chunks, embeddings)
        total_chunks += len(chunks)
        
    logger.info("ETL pipeline finished. Processed %d chunks in total.", total_chunks)

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "./kb"
    run_pipeline(target_dir)