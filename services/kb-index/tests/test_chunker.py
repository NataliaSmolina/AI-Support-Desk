from kb_index.chunker import chunk_markdown
from kb_index.models import Document


def make_doc(content: str, source_file: str = "kb/test.md") -> Document:
    """Create a Document object for chunker tests."""
    return Document(source_file=source_file, content=content)


def test_empty_document_returns_no_chunks():
    chunks = chunk_markdown(make_doc(""))

    assert chunks == []


def test_whitespace_only_document_returns_no_chunks():
    content = "   \n\n\t\n  \n"

    chunks = chunk_markdown(make_doc(content))

    assert chunks == []


def test_plain_text_without_headers_becomes_one_chunk():
    content = "Hello\nWorld"

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].text == "Hello\nWorld"
    assert chunks[0].headers == []
    assert chunks[0].source_file == "kb/test.md"


def test_single_header_and_text():
    content = "# Refunds\nMoney is returned in 3 days."

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].text == "Money is returned in 3 days."
    assert chunks[0].headers == ["Refunds"]


def test_two_sections_create_two_chunks():
    content = (
        "# FAQ\n"
        "Intro text\n"
        "## Refunds\n"
        "Refund text"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].text == "Intro text"
    assert chunks[0].headers == ["FAQ"]

    assert chunks[1].text == "Refund text"
    assert chunks[1].headers == ["FAQ", "Refunds"]


def test_text_before_first_header_has_empty_headers():
    content = (
        "Intro\n"
        "# Title\n"
        "Body"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].text == "Intro"
    assert chunks[0].headers == []

    assert chunks[1].text == "Body"
    assert chunks[1].headers == ["Title"]


def test_header_same_level_replaces_previous_header():
    content = (
        "## One\n"
        "text one\n"
        "## Two\n"
        "text two"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].headers == ["One"]
    assert chunks[0].text == "text one"

    assert chunks[1].headers == ["Two"]
    assert chunks[1].text == "text two"


def test_deeper_headers_are_attached_to_parent_headers():
    content = (
        "# Root\n"
        "## Section\n"
        "### Subsection\n"
        "Deep text"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Root", "Section", "Subsection"]
    assert chunks[0].text == "Deep text"


def test_going_back_to_h2_removes_h3_from_hierarchy():
    content = (
        "# Root\n"
        "## A\n"
        "text A\n"
        "### A1\n"
        "text A1\n"
        "## B\n"
        "text B"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 3

    assert chunks[0].headers == ["Root", "A"]
    assert chunks[0].text == "text A"

    assert chunks[1].headers == ["Root", "A", "A1"]
    assert chunks[1].text == "text A1"

    assert chunks[2].headers == ["Root", "B"]
    assert chunks[2].text == "text B"


def test_top_level_header_removes_all_previous_headers():
    content = (
        "# A\n"
        "## B\n"
        "### C\n"
        "text C\n"
        "# D\n"
        "text D"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].headers == ["A", "B", "C"]
    assert chunks[0].text == "text C"

    assert chunks[1].headers == ["D"]
    assert chunks[1].text == "text D"


def test_header_skip_levels():
    content = (
        "# H1\n"
        "### H3\n"
        "text\n"
        "## H2\n"
        "text2"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].headers == ["H1", "H3"]
    assert chunks[0].text == "text"

    assert chunks[1].headers == ["H1", "H2"]
    assert chunks[1].text == "text2"


def test_headers_without_text_do_not_create_chunks():
    content = (
        "# A\n"
        "## B\n"
        "### C"
    )

    chunks = chunk_markdown(make_doc(content))

    assert chunks == []


def test_empty_section_before_text_does_not_create_extra_chunk():
    content = (
        "# Empty\n"
        "## Also empty\n"
        "Some text"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Empty", "Also empty"]
    assert chunks[0].text == "Some text"


def test_consecutive_headers_wait_for_text():
    content = (
        "# A\n"
        "## B\n"
        "### C\n"
        "Text"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["A", "B", "C"]
    assert chunks[0].text == "Text"


def test_header_inside_code_block_is_not_treated_as_header():
    content = (
        "# Real\n"
        "Before\n"
        "```md\n"
        "# Fake\n"
        "```\n"
        "After"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Real"]
    assert chunks[0].text == "Before\n```md\n# Fake\n```\nAfter"


def test_code_block_before_any_header_creates_chunk_without_headers():
    content = (
        "```\n"
        "# Fake\n"
        "```\n"
        "# Real\n"
        "Body"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2

    assert chunks[0].headers == []
    assert chunks[0].text == "```\n# Fake\n```"

    assert chunks[1].headers == ["Real"]
    assert chunks[1].text == "Body"


def test_unclosed_code_block_keeps_remaining_lines_as_text():
    content = (
        "# Real\n"
        "```\n"
        "# Fake"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Real"]
    assert chunks[0].text == "```\n# Fake"


def test_header_without_space_is_not_header():
    content = "#NoHeader\nText"

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == []
    assert chunks[0].text == "#NoHeader\nText"


def test_header_with_extra_spaces_is_parsed():
    content = "  #   Title  \nText"

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Title"]
    assert chunks[0].text == "Text"


def test_six_level_header_is_supported():
    content = "###### Deep\nText"

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["Deep"]
    assert chunks[0].text == "Text"


def test_crlf_line_endings_are_supported():
    content = "# A\r\nText"

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 1
    assert chunks[0].headers == ["A"]
    assert chunks[0].text == "Text"


def test_source_file_is_propagated_to_chunks():
    doc = Document(
        source_file="kb/refunds.md",
        content="# Refunds\nText",
    )

    chunks = chunk_markdown(doc)

    assert len(chunks) == 1
    assert chunks[0].source_file == "kb/refunds.md"


def test_content_hash_is_filled_and_stable():
    first = chunk_markdown(make_doc("# A\nText"))[0]
    second = chunk_markdown(make_doc("# A\nText"))[0]

    assert first.content_hash
    assert first.content_hash == second.content_hash


def test_content_hash_changes_when_text_changes():
    first = chunk_markdown(make_doc("# A\nText 1"))[0]
    second = chunk_markdown(make_doc("# A\nText 2"))[0]

    assert first.content_hash != second.content_hash


def test_content_hash_changes_when_headers_change():
    first = chunk_markdown(make_doc("# A\nText"))[0]
    second = chunk_markdown(make_doc("# B\nText"))[0]

    assert first.content_hash != second.content_hash


def test_chunks_from_one_document_have_different_hashes():
    content = (
        "# A\n"
        "text one\n"
        "# B\n"
        "text two"
    )

    chunks = chunk_markdown(make_doc(content))

    assert len(chunks) == 2
    assert chunks[0].content_hash != chunks[1].content_hash