import hashlib
import json
import logging

from .chunker import Chunker
from .database import DBLoader
from .embedder import Embedder
from .loader import Loader

logger = logging.getLogger(__name__)

INDEX_VERSION = "markdown-header-v4"


def build_index_fingerprint(
    *,
    index_version: str,
    model_id: str,
    model_sha: str | None,
    tokenizer_sha256: str,
    chunk_max_tokens: int,
) -> str:
    """Стабильный отпечаток конфигурации индекса.

    Меняется при смене модели, tokenizer, лимита чанка или версии
    chunker/формата embedding_text.
    """
    payload = {
        "index_version": index_version,
        "model_id": model_id,
        "model_sha": model_sha,
        "tokenizer_sha256": tokenizer_sha256,
        "chunk_max_tokens": chunk_max_tokens,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Pipeline:
    def __init__(
        self,
        loader: Loader,
        chunker: Chunker,
        embedder: Embedder,
        db_loader: DBLoader,
        embed_batch_size: int,
        index_fingerprint: str = INDEX_VERSION,
    ):
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.db_loader = db_loader
        self.embed_batch_size = embed_batch_size
        self.index_fingerprint = index_fingerprint

    async def run(self):
        """Выполняет ETL пайплайн kb-index с записью в PostgreSQL"""
        logger.info(f"Starting kb-index pipeline. Source: {self.loader.source()}")
        logger.info(f"Index fingerprint: {self.index_fingerprint}")

        docs = self.loader.load()
        logger.info(f"Loaded {len(docs)} markdown documents.")

        total_new = 0
        total_skipped = 0
        total_skipped_docs = 0
        active_sources: list[str] = []

        for doc in docs:
            active_sources.append(doc.source_file)

            state = await self.db_loader.get_document_state(doc.source_file)
            if (
                state is not None
                and state.doc_hash == doc.doc_hash
                and state.index_version == self.index_fingerprint
            ):
                total_skipped_docs += 1
                logger.info(f"Skipped {doc.source_file}: unchanged document.")
                continue

            chunks = self.chunker.chunk(doc)
            valid_hashes = [c.content_hash for c in chunks]

            existing_hashes = await self.db_loader.get_existing_hashes(doc.source_file)
            force_reembed = (
                state is not None
                and state.index_version != self.index_fingerprint
            )
            if force_reembed:
                chunks_to_process = chunks
                logger.info(
                    f"Index configuration changed for {doc.source_file}: "
                    f"re-embedding all {len(chunks)} chunks."
                )
            else:
                chunks_to_process = [
                    c for c in chunks if c.content_hash not in existing_hashes
                ]
            total_skipped += len(chunks) - len(chunks_to_process)

            embeddings: list[list[float]] = []
            if chunks_to_process:
                logger.info(
                    f"Processing {doc.source_file}: {len(chunks_to_process)} new/changed "
                    f"chunks (skipped {len(chunks) - len(chunks_to_process)})"
                )
                for i in range(0, len(chunks_to_process), self.embed_batch_size):
                    batch = chunks_to_process[i:i + self.embed_batch_size]
                    embeddings.extend(
                        await self.embedder.embed([c.embedding_text for c in batch])
                    )
            else:
                logger.info(
                    f"Skipped {doc.source_file}: no chunk changes, updating document state."
                )

            result = await self.db_loader.sync_document(
                source_file=doc.source_file,
                doc_hash=doc.doc_hash,
                index_version=self.index_fingerprint,
                valid_hashes=valid_hashes,
                chunks_to_upsert=chunks_to_process,
                embeddings=embeddings,
            )
            total_new += result.upserted

        pruned = await self.db_loader.prune_missing_sources(active_sources)
        logger.info(
            f"Pipeline finished. Upserted: {total_new}, "
            f"Skipped chunks: {total_skipped}, "
            f"Skipped documents: {total_skipped_docs}, "
            f"Pruned documents: {pruned}"
        )
