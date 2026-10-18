import pytest
from kb_index.loader import LocalDirectoryLoader
from kb_index.models import Document


def test_load_reads_markdown_files_recursively(tmp_path):
    (tmp_path / "a.md").write_text("# A\ntext a", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.md").write_text("# B\ntext b", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not markdown", encoding="utf-8")

    documents = LocalDirectoryLoader(str(tmp_path)).load()

    assert len(documents) == 2
    assert all(isinstance(doc, Document) for doc in documents)
    assert {doc.content for doc in documents} == {"# A\ntext a", "# B\ntext b"}


def test_init_raises_for_missing_directory(tmp_path):
    with pytest.raises(ValueError, match="Directory not found"):
        LocalDirectoryLoader(str(tmp_path / "does_not_exist"))