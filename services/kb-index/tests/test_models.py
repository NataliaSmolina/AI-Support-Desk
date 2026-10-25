from kb_index.models import Document


def test_doc_hash_is_stable_for_same_source_and_content():
    first = Document(source_file="kb/a.md", content="# A\ntext")
    second = Document(source_file="kb/a.md", content="# A\ntext")

    assert first.doc_hash
    assert first.doc_hash == second.doc_hash


def test_doc_hash_reacts_to_content_and_source_changes():
    base = Document(source_file="kb/a.md", content="# A\ntext")

    assert base.doc_hash != Document(source_file="kb/a.md", content="# A\nother").doc_hash
    assert base.doc_hash != Document(source_file="kb/b.md", content="# A\ntext").doc_hash
