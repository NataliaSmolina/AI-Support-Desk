from kb_index.pipeline import build_index_fingerprint


def make_fingerprint(**overrides):
    params = {
        "index_version": "v1",
        "model_id": "BAAI/bge-m3",
        "model_sha": "abc",
        "tokenizer_sha256": "tokenizer-hash",
        "chunk_max_tokens": 512,
    }
    params.update(overrides)
    return build_index_fingerprint(**params)


def test_index_fingerprint_is_stable():
    assert make_fingerprint() == make_fingerprint()


def test_index_fingerprint_reacts_to_each_config_field():
    base = make_fingerprint()

    assert base != make_fingerprint(index_version="v2")
    assert base != make_fingerprint(model_id="other/model")
    assert base != make_fingerprint(model_sha="def")
    assert base != make_fingerprint(tokenizer_sha256="other-tokenizer")
    assert base != make_fingerprint(chunk_max_tokens=256)
