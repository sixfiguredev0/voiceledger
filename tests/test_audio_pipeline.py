import wave

import numpy as np
import pytest

from voiceledger.audio import AudioError, clip_wav, normalize_audio, place_on_clock, sha256_file
from voiceledger.pipeline import align_transcript, keep_core_words


def make_wav(path, duration=2, rate=48000):
    t = np.arange(int(rate * duration)) / rate
    samples = (np.sin(t * 2 * np.pi * 440) * 10000).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path


def test_decode_duration_hash_and_native_clip(tmp_path):
    source = make_wav(tmp_path / "native.wav")
    before = sha256_file(source)
    result = normalize_audio(source, tmp_path / "working.npy")
    assert sha256_file(source) == before
    assert result["normalized_samples"] == 32000
    assert result["decoded_duration_ms"] == 2000
    assert np.load(tmp_path / "working.npy").shape == (32000,)
    import io

    with wave.open(io.BytesIO(clip_wav(source, 500, 1500))) as clip:
        assert clip.getframerate() == 48000
        assert abs(clip.getnframes() - 48000) <= 1


def test_bad_audio_and_clip_bounds(tmp_path):
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio")
    with pytest.raises(AudioError):
        normalize_audio(bad, tmp_path / "working.npy")
    with pytest.raises(AudioError):
        clip_wav(bad, -1, 100)


def test_boundary_ownership_is_unique():
    words = [
        {"start_ms": 950, "end_ms": 1050, "text": " seam"},
        {"start_ms": 900, "end_ms": 980, "text": " before"},
    ]
    first = keep_core_words(words, 0, 1000)
    second = keep_core_words(words, 1000, 2000, True)
    assert first == [words[1]]
    assert second == [words[0]]


def test_source_clock_overlaps_and_gaps_are_accounted_for():
    samples = np.array([1, 2, 3], dtype=np.float32)
    trimmed, adjustment = place_on_clock(samples, -1)
    assert trimmed.tolist() == [2, 3] and adjustment == -1
    padded, adjustment = place_on_clock(samples, 1)
    assert padded.tolist() == [0, 1, 2, 3] and adjustment == 1


def test_alignment_preserves_overlap_unknown_and_missing_text():
    words = [
        {"start_ms": 100, "end_ms": 400, "text": "Здравей", "probability": 0.99},
        {"start_ms": 1200, "end_ms": 1500, "text": "hello", "probability": 0.3},
    ]
    diar = {
        "exclusive_turns": [
            {"start_ms": 0, "end_ms": 500, "cluster": "A"},
            {"start_ms": 2000, "end_ms": 3000, "cluster": "C"},
        ],
        "turns": [
            {"start_ms": 0, "end_ms": 500, "cluster": "A"},
            {"start_ms": 50, "end_ms": 500, "cluster": "B"},
        ],
    }
    rows = align_transcript("test", words, diar)
    assert rows[0]["overlap"] and rows[0]["uncertain"]
    assert rows[1]["cluster"] is None and rows[1]["uncertain"]
    assert rows[2]["category"] == "untranscribed"
    assert rows[0]["text"] == "Здравей"


def test_long_untranscribed_gaps_are_not_hidden_by_one_recognized_word():
    words = [{"start_ms": 0, "end_ms": 500, "text": "hello", "probability": 0.9}]
    turns = [{"start_ms": 0, "end_ms": 10000, "cluster": "A"}]
    rows = align_transcript("gap-test", words, {"turns": turns, "exclusive_turns": turns})
    assert any(
        row["category"] == "untranscribed" and row["start_ms"] == 500 and row["end_ms"] == 10000
        for row in rows
    )
