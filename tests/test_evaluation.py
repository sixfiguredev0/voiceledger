import pytest

from voiceledger.evaluation import evaluate, tokens, word_errors


def test_bulgarian_reference_normalization_and_real_edit_counts():
    assert tokens("Здравей, СВЯТ!") == ["здравей", "свят"]
    score = word_errors(["one", "two", "three"], ["one", "four", "three", "five"])
    assert score["substitutions"] == 1 and score["insertions"] == 1
    assert score["word_error_rate"] == pytest.approx(2 / 3)
    with pytest.raises(ValueError):
        word_errors([], ["hallucination"])


def test_speaker_coverage_does_not_give_a_merged_voice_perfect_accuracy():
    raw = [{"start_ms": 0, "end_ms": 2000, "text": "hello there", "cluster": "A", "words": []}]
    reviewed = [
        {"start_ms": 0, "end_ms": 1000, "text": "hello", "speaker_id": "person-1"},
        {"start_ms": 1000, "end_ms": 2000, "text": "there", "speaker_id": "person-2"},
    ]
    result = evaluate(raw, reviewed, {"person-1": "Alice", "person-2": "Bob"}, {"A": "Alice"})
    assert result["word_error_rate"] == 0
    assert result["speaker_attribution_accuracy"] == 0.5
    assert result["speaker_evaluated_ms"] == 2000
