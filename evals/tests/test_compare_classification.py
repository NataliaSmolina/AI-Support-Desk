from pathlib import Path

from ai_clients.llm import ClassificationError
from evals.compare_classification import evaluate_case, load_cases, summarize


def test_validation_set_has_no_baseline_questions():
    baseline = load_cases(Path('evals/data/classify_questions.json'))
    validation = load_cases(Path('evals/data/classify_validation.json'))
    questions = [case['question'] for case in validation]
    assert len(questions) == len(set(questions))
    assert not set(questions) & {case['question'] for case in baseline}


def test_errors_and_mismatches_count_against_accuracy():
    expected = {'category': 'billing', 'priority': 'normal', 'sentiment': 'calm', 'wants_human': False}
    rows = [dict(actual=expected, expected=expected, mismatches=[], elapsed_s=2),
            dict(actual={**expected, 'priority': 'low'}, expected=expected, mismatches=['priority'], elapsed_s=4),
            dict(actual=None, expected=expected, mismatches=['timeout'], elapsed_s=180)]
    result = summarize(rows)
    assert result['exact'] == 1
    assert result['errors'] == 1
    assert result['correct']['category'] == 2
    assert result['correct']['priority'] == 1
    assert result['mean_success_s'] == 3


async def test_failed_request_is_preserved():
    class Failed:
        async def classify(self, question):
            raise ClassificationError('timeout')
    row = await evaluate_case(Failed(), {'question': 'вопрос', 'expected': {}})
    assert row['actual'] is None
    assert row['mismatches'] == ['timeout']


async def test_comparison_saves_complete_report_and_nonzero_on_quality_failure(monkeypatch, tmp_path):
    import json
    import sys
    from ai_clients.llm import Classification
    from evals import compare_classification as module

    expected = {'category': 'billing', 'priority': 'normal', 'sentiment': 'calm', 'wants_human': False}
    seen = []
    closed = []

    class FakeClassifier:
        def __init__(self, *args, system_prompt, **kwargs):
            self.prompt = system_prompt
        async def classify(self, question):
            seen.append((self.prompt, question))
            return Classification(**{**expected, 'priority': 'low'})
        async def aclose(self):
            closed.append(self.prompt)

    async def ready(settings):
        pass
    async def version(*args):
        return 'test', None

    output = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['compare', '--output', str(output), '--limit', '1'])
    monkeypatch.setattr(module, 'check_llm_ready', ready)
    monkeypatch.setattr(module, 'read_server_version', version)
    monkeypatch.setattr(module, 'LlmClassifier', FakeClassifier)
    monkeypatch.setattr(module, 'load_cases', lambda path: [{'question': 'test', 'expected': expected}])
    assert await module.main() == 1
    report = json.loads(output.read_text())
    assert report['complete'] is True
    assert report['partial'] is True
    assert len(seen) == 6  # Two warmups plus two prompts for each of two datasets.
    assert len(closed) == 2
    assert report['datasets']['validation']['summary']['after']['exact'] == 0
