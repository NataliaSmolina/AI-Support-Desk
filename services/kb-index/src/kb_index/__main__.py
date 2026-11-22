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
from .pipeline import Pipeline
from .tokenization import HfTokenizerCounter, find_tokenizer_path

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
        logger.info(
            f"Tokenizer: {tokenizer_path} "
            f"(model={model_id}, max_tokens={max_tokens})"
        )

        pipeline = Pipeline(
            loader=LocalDirectoryLoader(settings.kb_dir),
            chunker=MarkdownHeaderChunker(
                tokenizer=tokenizer,
                max_tokens=max_tokens,
            ),
            embedder=TeiEmbedderAdapter(tei),
            db_loader=DBLoader(pool),
            embed_batch_size=settings.embed_batch_size,
        )
        await pipeline.run()
    finally:
        await tei.aclose()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
