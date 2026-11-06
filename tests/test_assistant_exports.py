import pytest
from pydantic import ValidationError

from voiceledger.assistant import anchor_selection, clean_environment, strict_schema
from voiceledger.exports import cell, timestamp
from voiceledger.schemas import Action, AssistantResponse


def test_assistant_schema_and_no_paid_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key")
    monkeypatch.setenv("CODEX_API_KEY", "private-test-key")
    assert "OPENAI_API_KEY" not in clean_environment()
    assert "CODEX_API_KEY" not in clean_environment()
    schema = strict_schema(AssistantResponse.model_json_schema())
    assert set(schema["required"]) == set(schema["properties"])
    assert not schema["additionalProperties"]
    action = Action(kind="reanalyze", start_ms=0, end_ms=1000, min_speakers=3)
    assert action.min_speakers == 3 and action.max_speakers is None
    with pytest.raises(ValidationError):
        Action(kind="execute", command="erase files")


def test_export_time_and_spreadsheet_formula_safety():
    assert timestamp(3_661_234, True) == "01:01:01,234"
    assert cell("=1+1") == "'=1+1"
    assert cell("Здравей") == "Здравей"


def test_implicit_recheck_bounds_come_from_selection_and_cannot_escape_it():
    context = {"selection": [{"id": "one", "start_ms": 1000, "end_ms": 5000}]}
    value = {"actions": [{"kind": "reanalyze", "row_ids": ["one"], "min_speakers": 3}]}
    anchored = anchor_selection(value, context)
    action = Action.model_validate(anchored["actions"][0])
    assert (action.start_ms, action.end_ms, action.min_speakers) == (1000, 5000, 3)
    action = anchor_selection({"actions": [{"kind": "reanalyze", "start_ms": 0, "end_ms": 900000}]}, context)[
        "actions"
    ][0]
    assert (action["start_ms"], action["end_ms"]) == (1000, 5000)
    with pytest.raises(ValueError):
        anchor_selection({"actions": [{"kind": "reanalyze", "row_ids": ["outside"]}]}, context)
