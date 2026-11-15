import asyncio
import logging

import asyncpg
from ai_clients.config import AISettings
from ai_clients.tei import TeiEmbedder

from .chunker import MarkdownHeaderChunker
from .config import Settings
from .database import DBLoader
from .embedder import TeiEmbedderAdapter
from .loader import LocalDirectoryLoader
from .pipeline import Pipeline

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
        pipeline = Pipeline(
            loader=LocalDirectoryLoader(settings.kb_dir),
            chunker=MarkdownHeaderChunker(),
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
