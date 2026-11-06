from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .audio import atomic_json
from .config import ASR_REPOS, DIARIZATION_REPO, MODES, PIPELINE_VERSION, SAMPLE_RATE, threads
from .models import cached_model


def artifact_key(source_hash: str, mode: str, language: str, revisions: dict) -> str:
    value = json.dumps([source_hash, mode, language, revisions, PIPELINE_VERSION], sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def model_revisions(root: Path, mode: str) -> dict:
    return {
        "asr": cached_model(root, ASR_REPOS[mode]).name,
        "diarization": cached_model(root, DIARIZATION_REPO).name,
        "faster_whisper": "1.2.1",
        "pyannote_audio": "4.0.7",
    }


def keep_core_words(words: list[dict], start_ms: int, end_ms: int, last: bool = False) -> list[dict]:
    """Assign each boundary-context word to exactly one half-open core interval."""
    return [
        w
        for w in words
        if start_ms <= (w["start_ms"] + w["end_ms"]) / 2 < end_ms
        or (last and (w["start_ms"] + w["end_ms"]) / 2 == end_ms)
    ]


def transcribe(
    audio_path: Path,
    model_path: Path,
    output_dir: Path,
    mode: str = "balanced",
    language: str = "bg",
    progress: Callable | None = None,
    region: tuple[int, int] | None = None,
    chunk_seconds: int = 600,
) -> dict:
    from faster_whisper import WhisperModel

    output_dir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(
        str(model_path), device="cpu", compute_type="int8", cpu_threads=threads(), num_workers=1
    )
    audio = np.load(audio_path, mmap_mode="r")
    total_ms = round(len(audio) * 1000 / SAMPLE_RATE)
    left, right = region or (0, total_ms)
    if not 0 <= left < right <= total_ms:
        raise ValueError("The selected region is outside this recording.")
    results = []
    cache_hits = 0
    count = math.ceil((right - left) / (chunk_seconds * 1000))
    started = time.perf_counter()
    for index in range(count):
        core_start = left + index * chunk_seconds * 1000
        core_end = min(right, core_start + chunk_seconds * 1000)
        chunk_path = output_dir / f"chunk-{index:05d}.json"
        if chunk_path.exists():
            cache_hits += 1
            words = json.loads(chunk_path.read_text(encoding="utf-8"))["words"]
        else:
            context_start = max(left, core_start - 2000)
            context_end = min(right, core_end + 2000)
            waveform = np.array(
                audio[round(context_start * SAMPLE_RATE / 1000) : round(context_end * SAMPLE_RATE / 1000)]
            )
            segments, _ = model.transcribe(
                waveform,
                language=None if language == "auto" else language,
                task="transcribe",
                beam_size=MODES[mode]["beam_size"],
                word_timestamps=True,
                vad_filter=True,
                condition_on_previous_text=False,
                temperature=0,
            )
            words = []
            for segment in segments:
                for word in segment.words or []:
                    start = max(left, round(word.start * 1000) + context_start)
                    end = min(right, round(word.end * 1000) + context_start)
                    if end > start:
                        words.append(
                            {
                                "start_ms": start,
                                "end_ms": end,
                                "text": word.word,
                                "probability": float(word.probability),
                            }
                        )
            words = keep_core_words(words, core_start, core_end, index == count - 1)
            atomic_json(chunk_path, {"start_ms": core_start, "end_ms": core_end, "words": words})
        results.extend(words)
        if progress:
            progress((index + 1) / count)
    result = {
        "words": results,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "model": MODES[mode]["model"],
        "language": language,
        "cached_sections": cache_hits,
    }
    atomic_json(output_dir / "transcript.json", result)
    return result


def diarize(
    audio_path: Path,
    model_path: Path,
    cache_dir: Path,
    output: Path,
    progress: Callable | None = None,
    region: tuple[int, int] | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_CACHE"] = str(cache_dir)
    import torch
    from pyannote.audio import Pipeline

    torch.set_num_threads(threads())
    pipeline = Pipeline.from_pretrained(str(model_path), cache_dir=str(cache_dir))
    # The downloaded Community-1 configuration uses GPU-oriented batches of 32.
    # Keep CPU memory bounded on 16 GB Windows machines.
    pipeline.segmentation_batch_size = 1
    pipeline.embedding_batch_size = 1
    waveform = np.load(audio_path, mmap_mode="r")
    left, right = region or (0, round(len(waveform) * 1000 / SAMPLE_RATE))
    waveform = waveform[round(left * SAMPLE_RATE / 1000) : round(right * SAMPLE_RATE / 1000)]
    # A writable copy avoids torchcodec/FFmpeg DLL coupling on Windows.
    tensor = torch.from_numpy(np.array(waveform, copy=True)).unsqueeze(0)
    started = time.perf_counter()
    last_progress = 0.0

    def hook(step, artifact, **kwargs):
        nonlocal last_progress
        if progress:
            positions = {
                "segmentation": (0, 0.45),
                "embeddings": (0.45, 0.45),
                "discrete_diarization": (0.9, 0.08),
                "clustering": (0.9, 0.05),
            }
            if step not in positions:
                return
            base, weight = positions[step]
            fraction = kwargs.get("completed", 0) / max(1, kwargs.get("total", 1)) if kwargs else 1
            last_progress = max(last_progress, base + weight * fraction)
            progress(last_progress)

    result = pipeline(
        {"waveform": tensor, "sample_rate": SAMPLE_RATE},
        hook=hook,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )

    def turns(annotation):
        return [
            {
                "start_ms": round(turn.start * 1000) + left,
                "end_ms": round(turn.end * 1000) + left,
                "cluster": str(speaker),
            }
            for turn, speaker in annotation
        ]

    labels = result.speaker_diarization.labels()
    embeddings = {}
    if result.speaker_embeddings is not None:
        for label, embedding in zip(labels, result.speaker_embeddings):
            norm = float(np.linalg.norm(embedding))
            if norm > 1e-8 and np.isfinite(embedding).all():
                embeddings[str(label)] = (embedding / norm).tolist()
    payload = {
        "turns": turns(result.speaker_diarization),
        "exclusive_turns": turns(result.exclusive_speaker_diarization),
        "embeddings": embeddings,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "region": [left, right],
    }
    atomic_json(output, payload)
    return payload


def reference_embedding(
    audio_path: Path, model_path: Path, cache_dir: Path, start_ms: int, end_ms: int
) -> list:
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

    torch.set_num_threads(threads())
    model = PretrainedSpeakerEmbedding(
        {"checkpoint": str(model_path), "subfolder": "embedding"}, cache_dir=str(cache_dir)
    )
    audio = np.load(audio_path, mmap_mode="r")
    clip = np.array(audio[round(start_ms * SAMPLE_RATE / 1000) : round(end_ms * SAMPLE_RATE / 1000)])
    if len(clip) < SAMPLE_RATE:
        raise ValueError("Use at least one second of clean speech for a reference sample.")
    vector = model(torch.from_numpy(clip)[None, None])[0]
    norm = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or norm < 1e-8:
        raise ValueError("This clip did not produce a valid voice embedding.")
    return (vector / norm).tolist()


def align_transcript(recording_id: str, words: list[dict], diarization: dict) -> list[dict]:
    exclusive = sorted(diarization["exclusive_turns"], key=lambda t: t["start_ms"])
    regular = diarization["turns"]
    rows = []
    cursor = 0
    for index, word in enumerate(words):
        start, end = word["start_ms"], word["end_ms"]
        while cursor < len(exclusive) and exclusive[cursor]["end_ms"] <= start:
            cursor += 1
        candidates = []
        for turn in exclusive[cursor:]:
            if turn["start_ms"] >= end:
                break
            overlap = min(end, turn["end_ms"]) - max(start, turn["start_ms"])
            if overlap > 0:
                candidates.append((overlap, turn["cluster"]))
        cluster = max(candidates)[1] if candidates else None
        active_turns = [turn for turn in regular if min(end, turn["end_ms"]) > max(start, turn["start_ms"])]
        overlap = any(
            a["cluster"] != b["cluster"]
            and min(end, a["end_ms"], b["end_ms"]) > max(start, a["start_ms"], b["start_ms"])
            for i, a in enumerate(active_turns)
            for b in active_turns[i + 1 :]
        )
        boundary_uncertain = bool(candidates and max(candidates)[0] < (end - start) * 0.6)
        uncertain = cluster is None or word.get("probability", 1) < 0.4 or overlap or boundary_uncertain
        # A single row cannot span a speaker change, long pause or more than 12 seconds.
        if (
            rows
            and rows[-1]["cluster"] == cluster
            and rows[-1]["overlap"] == overlap
            and start - rows[-1]["end_ms"] < 1200
            and end - rows[-1]["start_ms"] < 12000
        ):
            row = rows[-1]
            row["end_ms"] = end
            row["text"] += word["text"]
            row["words"].append(word)
            row["uncertain"] = row["uncertain"] or uncertain
        else:
            row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{recording_id}:{start}:{index}"))
            rows.append(
                {
                    "id": row_id,
                    "recording_id": recording_id,
                    "start_ms": start,
                    "end_ms": end,
                    "cluster": cluster,
                    "speaker_id": None,
                    "text": word["text"].lstrip(),
                    "words": [word],
                    "overlap": overlap,
                    "uncertain": uncertain,
                    "excluded": False,
                    "category": "speech",
                    "manual": False,
                }
            )
    # Preserve diarized speech that ASR failed to transcribe for manual review.
    coverage = sorted((w["start_ms"], w["end_ms"]) for w in words)
    coverage_cursor = 0
    for turn in exclusive:
        if turn["end_ms"] - turn["start_ms"] < 500:
            continue
        while coverage_cursor < len(coverage) and coverage[coverage_cursor][1] <= turn["start_ms"]:
            coverage_cursor += 1
        point = turn["start_ms"]
        gaps = []
        index = coverage_cursor
        any_word = False
        while index < len(coverage) and coverage[index][0] < turn["end_ms"]:
            start, end = coverage[index]
            if start - point >= 1500:
                gaps.append((point, min(start, turn["end_ms"])))
            point = max(point, min(end, turn["end_ms"]))
            any_word = True
            index += 1
        if turn["end_ms"] - point >= (1500 if any_word else 500):
            gaps.append((point, turn["end_ms"]))
        for start, end in gaps:
            rows.append(
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{recording_id}:untranscribed:{start}")),
                    "recording_id": recording_id,
                    "start_ms": start,
                    "end_ms": end,
                    "cluster": turn["cluster"],
                    "speaker_id": None,
                    "text": "",
                    "words": [],
                    "overlap": False,
                    "uncertain": True,
                    "excluded": False,
                    "category": "untranscribed",
                    "manual": False,
                }
            )
    return sorted(rows, key=lambda r: r["start_ms"])
