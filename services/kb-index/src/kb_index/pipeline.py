import asyncio
import logging
from pathlib import Path

import asyncpg

from .chunker import chunk_markdown
from .config import settings
from .database import cleanup_orphans, get_existing_hashes, init_db, upsert_chunks
from .embedder import embed_texts
from .models import Document

logger = logging.getLogger(__name__)

def load_documents(directory: str) -> list[Document]:
    """Читает kb/*.md (Блок 1 схемы)"""
    documents = []
    path = Path(directory)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory not found: {directory}")
    
    for file_path in path.rglob("*.md"):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            documents.append(Document(source_file=str(file_path), content=content))
    return documents

async def run_pipeline():
    """Выполняет ETL пайплайн kb-index с записью в PostgreSQL"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    logger.info(f"Starting kb-index pipeline. Source: {settings.kb_dir}")
    
    # 1. Подключение к БД (Блок 4 схемы)
    logger.info("Connecting to PostgreSQL...")
    try:
        pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return
        
    await init_db(pool)

    # 2. Чтение документов
    docs = load_documents(settings.kb_dir)
    logger.info(f"Loaded {len(docs)} markdown documents.")

    total_new = 0
    total_skipped = 0

    # 3. Обработка каждого документа
    for doc in docs:
        # Чанкинг по заголовкам (Блок 2 схемы)
        chunks = chunk_markdown(doc)
        if not chunks:
            await cleanup_orphans(pool, doc.source_file, [])
            continue
        
        # Инкрементальность: проверяем, что уже есть в БД
        existing_hashes = await get_existing_hashes(pool, doc.source_file)
        chunks_to_process = [c for c in chunks if c.content_hash not in existing_hashes]
        total_skipped += (len(chunks) - len(chunks_to_process))

        if chunks_to_process:
            logger.info(f"Processing {doc.source_file}: {len(chunks_to_process)} new/changed chunks (skipped {len(chunks) - len(chunks_to_process)})")
            
            # Векторизация (Блок 3 схемы)
            for i in range(0, len(chunks_to_process), settings.embed_batch_size):
                batch = chunks_to_process[i:i + settings.embed_batch_size]
                texts = [c.text for c in batch]
                
                embeddings = await embed_texts(texts)
                await upsert_chunks(pool, batch, embeddings)
                total_new += len(batch)
        else:
            logger.info(f"Skipped {doc.source_file}: no changes detected.")

        # Очистка удаленных из файла чанков
        valid_hashes = [c.content_hash for c in chunks]
        await cleanup_orphans(pool, doc.source_file, valid_hashes)

    logger.info(f"Pipeline finished. Upserted: {total_new}, Skipped (unchanged): {total_skipped}")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(run_pipeline())