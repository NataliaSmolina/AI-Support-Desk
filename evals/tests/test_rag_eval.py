from ai_clients.rag import RagResult, RagTimings
from ai_clients.retrieval import RetrievedChunk
from evals.check_rag import check_result, error_types


def test_eval_checks_fact_and_source_from_real_hash():
    result = RagResult(
        answer="Возврат за 10 дней.", source_ids=["real-content-hash"], needs_escalation=False,
        reason=None, timings=RagTimings(), retrieved_chunks=[
            RetrievedChunk("real-content-hash", "Текст", "/some/path/refunds.md", (), 0.1)],
    )
    expected = dict(answer_present=True, source_files=["refunds.md"], needs_escalation=False,
                    required_facts=["10 дней", "на карту"])
    errors = check_result(expected, result)
    assert errors == ["в ответе отсутствует обязательный факт: 'на карту'"]


def test_eval_reports_missing_retrieval_source():
    result = RagResult(answer=None, source_ids=[], needs_escalation=True, reason="no_documents",
                       timings=RagTimings(), retrieved_chunks=[])
    expected = dict(answer_present=True, source_files=["refunds.md"], needs_escalation=False,
                    required_facts=[])
    assert "Поиск не вернул обязательный источник: refunds.md" in check_result(expected, result)


def test_multiple_chunks_of_one_file_are_valid_sources():
    result = RagResult(answer="Ответ", source_ids=["a", "b"], needs_escalation=False,
                       reason=None, timings=RagTimings(), retrieved_chunks=[
                           RetrievedChunk("a", "Текст 1", "refunds.md", (), 0),
                           RetrievedChunk("b", "Текст 2", "refunds.md", (), 0.1)])
    expected = dict(answer_present=True, source_files=["refunds.md"], needs_escalation=False,
                    required_facts=[])
    assert check_result(expected, result) == []


def test_error_types_do_not_include_private_messages():
    from ai_clients.rag import RagError
    cause = TimeoutError("private request text")
    error = RagError("generation", "private URL")
    error.__cause__ = cause
    assert error_types(error) == ["RagError", "TimeoutError"]
