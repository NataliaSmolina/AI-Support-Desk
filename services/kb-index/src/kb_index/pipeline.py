import logging

from .chunker import Chunker
from .database import DBLoader
from .embedder import Embedder
from .loader import Loader

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, loader: Loader, chunker: Chunker, embedder: Embedder, db_loader: DBLoader, embed_batch_size: int):
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.db_loader = db_loader
        self.embed_batch_size = embed_batch_size

    async def run(self):
        """Выполняет ETL пайплайн kb-index с записью в PostgreSQL"""
        logger.info(f"Starting kb-index pipeline. Source: {self.loader.source()}")
        
        await self.db_loader.init()

        docs = self.loader.load()
        logger.info(f"Loaded {len(docs)} markdown documents.")

        total_new = 0
        total_skipped = 0

        for doc in docs:
            chunks = self.chunker.chunk(doc)
            if not chunks:
                await self.db_loader.cleanup_orphans(doc.source_file, [])
                continue
            
            existing_hashes = await self.db_loader.get_existing_hashes(doc.source_file)
            chunks_to_process = [c for c in chunks if c.content_hash not in existing_hashes]
            total_skipped += (len(chunks) - len(chunks_to_process))

            if chunks_to_process:
                logger.info(f"Processing {doc.source_file}: {len(chunks_to_process)} new/changed chunks (skipped {len(chunks) - len(chunks_to_process)})")
                
                for i in range(0, len(chunks_to_process), self.embed_batch_size):
                    batch = chunks_to_process[i:i + self.embed_batch_size]
                    texts = [c.text for c in batch]
                    
                    embeddings = await self.embedder.embed(texts)
                    await self.db_loader.upsert_chunks(batch, embeddings)
                    total_new += len(batch)
            else:
                logger.info(f"Skipped {doc.source_file}: no changes detected.")

            valid_hashes = [c.content_hash for c in chunks]
            await self.db_loader.cleanup_orphans(doc.source_file, valid_hashes)

        logger.info(f"Pipeline finished. Upserted: {total_new}, Skipped (unchanged): {total_skipped}")
