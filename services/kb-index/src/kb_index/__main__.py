import asyncio
import logging
from pathlib import Path

import asyncpg
from ai_clients.config import AISettings
from ai_clients.tei import TeiEmbedder

from .chunker import MarkdownHeaderChunker
from .config import Settings
from .database import DBLoader
from .embedder import TeiEmbedderAdapter
from .loader import LocalDirectoryLoader
from .pipeline import INDEX_VERSION, Pipeline, build_index_fingerprint
from .tokenization import HfTokenizerCounter, find_tokenizer_path, sha256_file

logger = logging.getLogger(__name__)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    settings = Settings()
    ai_settings = AISettings()
    logger.info(f"Starting kb-index pipeline. Source: {settings.kb_dir}")

    logger.info("Connecting to PostgreSQL...")
    try:
        pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    except Exception:
        logger.exception("Failed to connect to database")
        raise

    tei = TeiEmbedder(
        base_url=ai_settings.tei_embed_url,
        timeout_s=ai_settings.request_timeout_s,
    )
    try:
        info = await tei.get_info()
        model_id = str(info.get("model_id") or settings.tokenizer_model)
        max_tokens = settings.chunk_max_tokens
        tei_max_tokens = info.get("max_input_length")
        if isinstance(tei_max_tokens, int) and tei_max_tokens > 0:
            max_tokens = min(max_tokens, tei_max_tokens)

        tokenizer_path = (
            Path(settings.tokenizer_path)
            if settings.tokenizer_path
            else find_tokenizer_path(
                model_id,
                settings.tokenizer_cache_dir,
            )
        )
        tokenizer = HfTokenizerCounter(tokenizer_path)
        tokenizer_sha256 = sha256_file(tokenizer_path)
        model_sha = info.get("model_sha")
        if not isinstance(model_sha, str):
            model_sha = None
        index_fingerprint = build_index_fingerprint(
            index_version=INDEX_VERSION,
            model_id=model_id,
            model_sha=model_sha,
            tokenizer_sha256=tokenizer_sha256,
            chunk_max_tokens=max_tokens,
        )
        logger.info(
            f"Tokenizer: {tokenizer_path} "
            f"(model={model_id}, max_tokens={max_tokens})"
        )
        logger.info(f"Index fingerprint: {index_fingerprint}")

        pipeline = Pipeline(
            loader=LocalDirectoryLoader(settings.kb_dir),
            chunker=MarkdownHeaderChunker(
                tokenizer=tokenizer,
                max_tokens=max_tokens,
            ),
            embedder=TeiEmbedderAdapter(tei),
            db_loader=DBLoader(pool),
            embed_batch_size=settings.embed_batch_size,
            index_fingerprint=index_fingerprint,
        )
        await pipeline.run()
    finally:
        await tei.aclose()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
