from __future__ import annotations

import pytest
from kb_index.database import DBLoader
from kb_index.models import Chunk


def make_loader(dimension: int = 3) -> DBLoader:
    return DBLoader(pool=None, embedding_dimension=dimension)  # type: ignore[arg-type]


def make_chunk(text: str = "text", source_file: str = "kb/a.md") -> Chunk:
    return Chunk(text=text, headers=("A",), source_file=source_file)


@pytest.mark.asyncio
async def test_prune_missing_sources_skips_empty_active_set():
    loader = make_loader()

    assert await loader.prune_missing_sources([]) == 0


@pytest.mark.asyncio
async def test_sync_document_rejects_embedding_count_mismatch():
    loader = make_loader()
    chunk = make_chunk()

    with pytest.raises(ValueError, match="Chunk/embedding count mismatch"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[chunk.content_hash],
            chunks_to_upsert=[chunk],
            embeddings=[],
        )


@pytest.mark.asyncio
async def test_sync_document_rejects_wrong_embedding_dimension():
    loader = make_loader(dimension=3)
    chunk = make_chunk()

    with pytest.raises(ValueError, match="dimension 2, expected 3"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[chunk.content_hash],
            chunks_to_upsert=[chunk],
            embeddings=[[0.1, 0.2]],
        )


@pytest.mark.asyncio
async def test_sync_document_rejects_non_finite_embedding():
    loader = make_loader(dimension=3)
    chunk = make_chunk()

    with pytest.raises(ValueError, match="non-finite or non-numeric"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[chunk.content_hash],
            chunks_to_upsert=[chunk],
            embeddings=[[0.1, float("nan"), 0.3]],
        )


@pytest.mark.asyncio
async def test_sync_document_rejects_foreign_chunk_source():
    loader = make_loader()
    chunk = make_chunk(source_file="kb/b.md")

    with pytest.raises(ValueError, match="does not match"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[chunk.content_hash],
            chunks_to_upsert=[chunk],
            embeddings=[[0.1, 0.2, 0.3]],
        )


@pytest.mark.asyncio
async def test_sync_document_rejects_chunk_not_in_valid_hashes():
    loader = make_loader()
    chunk = make_chunk()

    with pytest.raises(ValueError, match="is not in valid_hashes"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[],
            chunks_to_upsert=[chunk],
            embeddings=[[0.1, 0.2, 0.3]],
        )


@pytest.mark.asyncio
async def test_sync_document_rejects_duplicate_chunk_hashes():
    loader = make_loader()
    first = make_chunk()
    second = make_chunk()

    with pytest.raises(ValueError, match="Duplicate chunk hash"):
        await loader.sync_document(
            source_file="kb/a.md",
            doc_hash="doc-hash",
            index_version="v1",
            valid_hashes=[first.content_hash],
            chunks_to_upsert=[first, second],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        )
