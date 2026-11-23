"""Unit-тесты используют маленький локальный токенизатор без скачивания моделей."""

import pytest


@pytest.fixture(scope="session")
def local_tokenizer_path(tmp_path_factory):
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    from transformers import PreTrainedTokenizerFast

    special = ["[UNK]", "[CLS]", "[SEP]", "<|im_start|>", "<|im_end|>", "<think>", "</think>"]
    backend = Tokenizer(models.WordLevel({token: i for i, token in enumerate(special)}, unk_token="[UNK]"))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    backend.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)],
    )
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="[UNK]", cls_token="[CLS]", sep_token="[SEP]",
        additional_special_tokens=special[3:], model_max_length=100_000,
    )
    tokenizer.chat_template = (
        "{% for message in messages %}"
        "{{ '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}"
        "{% endfor %}"
        "{% if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}"
        "{% if enable_thinking is defined and not enable_thinking %}{{ '<think>\n\n</think>\n\n' }}{% endif %}"
        "{% endif %}"
    )
    path = tmp_path_factory.mktemp("tokenizer")
    tokenizer.save_pretrained(path)
    return str(path)


@pytest.fixture(autouse=True)
def offline_tokenizers(monkeypatch, local_tokenizer_path):
    monkeypatch.setenv("TEI_TOKENIZER", local_tokenizer_path)
    monkeypatch.setenv("LLM_TOKENIZER", local_tokenizer_path)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TOKENIZER_LOCAL_FILES_ONLY", "true")
