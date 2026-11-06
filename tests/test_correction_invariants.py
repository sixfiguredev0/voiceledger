import copy

import pytest

from voiceledger.corrections import apply_rows


def test_recheck_and_global_merge_do_not_require_old_turn_ids():
    row = {"id": "new-turn", "speaker_id": "a", "start_ms": 0, "end_ms": 1000}
    assert apply_rows([row], {"kind": "reanalyze", "row_ids": ["old-turn"]}) == [row]
    merged = apply_rows(
        [row],
        {"kind": "merge", "row_ids": ["other-recording-turn"], "source_speaker_id": "a", "speaker_id": "b"},
    )
    assert merged[0]["speaker_id"] == "b"


def test_invalid_split_does_not_partially_change_replayed_rows():
    rows = [
        {
            "id": "turn",
            "speaker_id": None,
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Manually edited text",
            "words": [],
        }
    ]
    before = copy.deepcopy(rows)
    with pytest.raises(ValueError):
        apply_rows(rows, {"kind": "split", "row_ids": ["turn"], "split_at_ms": 500}, replay=True)
    assert rows == before
