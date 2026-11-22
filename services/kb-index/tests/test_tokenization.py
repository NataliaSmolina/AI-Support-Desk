import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from kb_index.tokenization import HfTokenizerCounter, find_tokenizer_path


def write_tokenizer(path):
    tokenizer = Tokenizer(
        WordLevel(
            {"hello": 0, "world": 1, "one": 2, "two": 3, "[UNK]": 4},
            unk_token="[UNK]",
        )
    )
    tokenizer.pre_tokenizer = Whitespace()
    path.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(path))
    return path


def test_hf_tokenizer_counter_counts_tokens(tmp_path):
    path = write_tokenizer(tmp_path / "tokenizer.json")
    counter = HfTokenizerCounter(path)

    assert counter.count("hello world") == 2
    assert counter.count("hello unknown") == 2


def test_find_tokenizer_path_in_tei_cache(tmp_path):
    path = write_tokenizer(
        tmp_path
        / "models--BAAI--bge-m3"
        / "snapshots"
        / "abc123"
        / "tokenizer.json"
    )

    found = find_tokenizer_path("BAAI/bge-m3", tmp_path)

    assert found == path


def test_find_tokenizer_path_raises_for_missing_model(tmp_path):
    with pytest.raises(FileNotFoundError, match="tokenizer.json"):
        find_tokenizer_path("BAAI/bge-m3", tmp_path)
