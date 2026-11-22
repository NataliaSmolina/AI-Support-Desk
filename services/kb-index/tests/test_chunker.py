import pytest
from kb_index.chunker import MarkdownHeaderChunker
from kb_index.models import Document


class WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def chunker() -> MarkdownHeaderChunker:
    return MarkdownHeaderChunker(WordCounter(), max_tokens=1000)


def make_doc(content: str, source_file: str = "kb/test.md") -> Document:
    return Document(source_file=source_file, content=content)


@pytest.mark.parametrize("content", ["", "   \n\n\t\n  \n", "# A\n## B\n### C"])
def test_no_text_means_no_chunks(chunker, content):
    """Пустой документ, только пробелы или заголовки без текста не дают чанков."""
    assert chunker.chunk(make_doc(content)) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Hello\nWorld", [([], "Hello\nWorld")]),
        ("# Refunds\nMoney is returned in 3 days.", [(["Refunds"], "Money is returned in 3 days.")]),
        (
            "# FAQ\nIntro text\n## Refunds\nRefund text",
            [(["FAQ"], "Intro text"), (["FAQ", "Refunds"], "Refund text")],
        ),
        ("Intro\n# Title\nBody", [([], "Intro"), (["Title"], "Body")]),
        (
            "## One\ntext one\n## Two\ntext two",
            [(["One"], "text one"), (["Two"], "text two")],
        ),
        (
            "# Root\n## Section\n### Subsection\nDeep text",
            [(["Root", "Section", "Subsection"], "Deep text")],
        ),
        (
            "# Root\n## A\ntext A\n### A1\ntext A1\n## B\ntext B",
            [
                (["Root", "A"], "text A"),
                (["Root", "A", "A1"], "text A1"),
                (["Root", "B"], "text B"),
            ],
        ),
        (
            "# A\n## B\n### C\ntext C\n# D\ntext D",
            [(["A", "B", "C"], "text C"), (["D"], "text D")],
        ),
        (
            "# H1\n### H3\ntext\n## H2\ntext2",
            [(["H1", "H3"], "text"), (["H1", "H2"], "text2")],
        ),
        (
            "# Empty\n## Also empty\nSome text",
            [(["Empty", "Also empty"], "Some text")],
        ),
    ],
)
def test_header_hierarchy(chunker, content, expected):
    """Заголовки формируют корректную иерархию и границы чанков."""
    chunks = chunker.chunk(make_doc(content))
    assert [(list(c.headers), c.text) for c in chunks] == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "# Real\nBefore\n```md\n# Fake\n```\nAfter",
            [(["Real"], "Before\n```md\n# Fake\n```\nAfter")],
        ),
        (
            "```\n# Fake\n```\n# Real\nBody",
            [([], "```\n# Fake\n```"), (["Real"], "Body")],
        ),
        ("# Real\n```\n# Fake", [(["Real"], "```\n# Fake")]),
    ],
)
def test_code_blocks_are_not_parsed_as_headers(chunker, content, expected):
    """Заголовки внутри блоков кода (```) игнорируются."""
    chunks = chunker.chunk(make_doc(content))
    assert [(list(c.headers), c.text) for c in chunks] == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("#NoHeader\nText", [([], "#NoHeader\nText")]),
        ("  #   Title  \nText", [(["Title"], "Text")]),
        ("###### Deep\nText", [(["Deep"], "Text")]),
        ("# A\r\nText", [(["A"], "Text")]),
    ],
)
def test_header_syntax_edge_cases(chunker, content, expected):
    """Отсутствие пробела после #, 6-й уровень, CRLF — граничные случаи синтаксиса."""
    chunks = chunker.chunk(make_doc(content))
    assert [(list(c.headers), c.text) for c in chunks] == expected


def test_source_file_is_propagated_to_chunks(chunker):
    chunks = chunker.chunk(make_doc("# Refunds\nText", source_file="kb/refunds.md"))

    assert len(chunks) == 1
    assert chunks[0].source_file == "kb/refunds.md"


def test_content_hash_is_stable_and_reacts_to_changes(chunker):
    base = chunker.chunk(make_doc("# A\nText"))[0]
    same = chunker.chunk(make_doc("# A\nText"))[0]
    other_text = chunker.chunk(make_doc("# A\nText 2"))[0]
    other_headers = chunker.chunk(make_doc("# B\nText"))[0]

    assert base.content_hash
    assert base.content_hash == same.content_hash
    assert base.content_hash != other_text.content_hash
    assert base.content_hash != other_headers.content_hash


def test_chunks_from_one_document_have_different_hashes(chunker):
    chunks = chunker.chunk(make_doc("# A\ntext one\n# B\ntext two"))

    assert len(chunks) == 2
    assert chunks[0].content_hash != chunks[1].content_hash


def test_content_hash_includes_source_file(chunker):
    first = chunker.chunk(make_doc("# A\nSame text", source_file="kb/first.md"))[0]
    second = chunker.chunk(make_doc("# A\nSame text", source_file="kb/second.md"))[0]

    assert first.content_hash != second.content_hash


def test_large_section_is_split_by_paragraphs():
    counter = WordCounter()
    chunker = MarkdownHeaderChunker(counter, max_tokens=6)
    content = (
        "# Policy\n"
        "First short sentence.\n"
        "\n"
        "Second short sentence."
    )

    chunks = chunker.chunk(make_doc(content))

    assert [chunk.text for chunk in chunks] == [
        "First short sentence.",
        "Second short sentence.",
    ]
    assert all(chunk.headers == ("Policy",) for chunk in chunks)
    assert all(counter.count(chunk.embedding_text) <= 6 for chunk in chunks)


def test_large_paragraph_is_split_by_sentences():
    counter = WordCounter()
    chunker = MarkdownHeaderChunker(counter, max_tokens=5)
    content = "# Policy\nFirst sentence. Second sentence. Third sentence."

    chunks = chunker.chunk(make_doc(content))

    assert [chunk.text for chunk in chunks] == [
        "First sentence. Second sentence.",
        "Third sentence.",
    ]
    assert all(counter.count(chunk.embedding_text) <= 5 for chunk in chunks)


def test_long_sentence_is_split_by_tokens_and_text_is_preserved():
    counter = WordCounter()
    chunker = MarkdownHeaderChunker(counter, max_tokens=4)
    content = "# Policy\none two three four five six."

    chunks = chunker.chunk(make_doc(content))

    assert len(chunks) > 1
    assert all(counter.count(chunk.embedding_text) <= 4 for chunk in chunks)
    assert " ".join(chunk.text for chunk in chunks).split() == [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six.",
    ]
    assert all(chunk.headers == ("Policy",) for chunk in chunks)


def test_headers_are_included_in_embedding_text_after_split():
    counter = WordCounter()
    chunker = MarkdownHeaderChunker(counter, max_tokens=5)
    content = "# Root\n## Section\nFirst sentence. Second sentence. Third sentence."

    chunks = chunker.chunk(make_doc(content))

    assert all(chunk.headers == ("Root", "Section") for chunk in chunks)
    assert all(
        chunk.embedding_text.startswith("Root → Section\n\n")
        for chunk in chunks
    )
