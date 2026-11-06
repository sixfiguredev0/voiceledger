from __future__ import annotations

import hashlib
import io
import json
import os
import wave
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from .config import SAMPLE_RATE


class AudioError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_audio(path: Path) -> dict:
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise AudioError("The file contains no audio stream.")
            stream = container.streams.audio[0]
            duration = (
                float(stream.duration * stream.time_base)
                if stream.duration is not None
                else float(container.duration or 0) / av.time_base
            )
            if duration <= 0:
                raise AudioError("The audio duration is missing or invalid.")
            return {
                "codec": stream.codec_context.name,
                "sample_rate": stream.codec_context.sample_rate,
                "channels": stream.codec_context.channels,
                "duration_ms": round(duration * 1000),
                "stream_start_ms": round(float((stream.start_time or 0) * stream.time_base) * 1000),
                "size_bytes": path.stat().st_size,
            }
    except (av.error.FFmpegError, OSError) as exc:
        raise AudioError(f"Cannot read this audio file: {type(exc).__name__}") from exc


def atomic_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def normalize_audio(path: Path, output: Path, progress: Callable | None = None) -> dict:
    """Decode the entire stream, preserving its presentation clock and detecting discontinuities."""
    metadata = inspect_audio(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output.with_suffix(".pcm.tmp")
    sample_count = 0
    last_end = None
    first_pts = None
    discontinuities = []
    peak_count = 0
    peaks = []
    peak_buffer = np.empty(0, dtype=np.float32)
    native_cursor = 0
    adjusted_samples = 0
    progress_bucket = -1
    try:
        with av.open(str(path)) as container, raw_path.open("wb") as raw:
            stream = container.streams.audio[0]
            native_rate = stream.codec_context.sample_rate
            native_converter = av.AudioResampler(format="fltp", layout="mono", rate=native_rate)
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)

            def write_frame(frame):
                nonlocal sample_count, peak_count, peak_buffer
                samples = frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                if not np.isfinite(samples).all():
                    raise AudioError("Decoder produced non-finite audio samples.")
                raw.write(samples.tobytes())
                sample_count += len(samples)
                peak_buffer = np.concatenate((peak_buffer, samples))
                width = SAMPLE_RATE // 10
                complete = len(peak_buffer) // width
                if complete:
                    blocks = peak_buffer[: complete * width].reshape(complete, width)
                    peaks.extend(np.max(np.abs(blocks), axis=1).round(4).tolist())
                    peak_count += complete
                    peak_buffer = peak_buffer[complete * width :]

            for frame in container.decode(stream):
                if frame.pts is not None:
                    pts = float(frame.pts * frame.time_base)
                    if first_pts is None:
                        first_pts = pts
                    if last_end is not None and abs(pts - last_end) > 0.1:
                        discontinuities.append(round((pts - last_end) * 1000))
                    last_end = pts + frame.samples / frame.sample_rate
                # Samsung AAC may contain occasional one-sample timestamp overlaps.
                # Place decoded samples on the source presentation clock before resampling.
                for native in native_converter.resample(frame):
                    native_samples = native.to_ndarray().reshape(-1)
                    expected = round((float(native.pts * native.time_base) - (first_pts or 0)) * native_rate)
                    delta = expected - native_cursor
                    if abs(delta) > native_rate * 0.1:
                        raise AudioError("Audio timestamps contain a gap or overlap larger than 100 ms.")
                    native_samples, adjustment = place_on_clock(native_samples, delta)
                    adjusted_samples += adjustment
                    if not len(native_samples):
                        continue
                    aligned = av.AudioFrame.from_ndarray(
                        native_samples[None, :], format="fltp", layout="mono"
                    )
                    aligned.sample_rate = native_rate
                    aligned.time_base = Fraction(1, native_rate)
                    aligned.pts = native_cursor
                    native_cursor += len(native_samples)
                    for normalized in resampler.resample(aligned):
                        write_frame(normalized)
                bucket = sample_count // (SAMPLE_RATE * 30)
                if progress and bucket != progress_bucket:
                    progress_bucket = bucket
                    progress(min(0.99, sample_count / SAMPLE_RATE / (metadata["duration_ms"] / 1000)))
            for normalized in resampler.resample(None):
                write_frame(normalized)
            if len(peak_buffer):
                peaks.append(round(float(np.max(np.abs(peak_buffer))), 4))
        if not sample_count:
            raise AudioError("The file decoded to zero samples.")
        if discontinuities:
            raise AudioError("Audio timestamps contain gaps or jumps; review the source before processing.")
        decoded_ms = sample_count * 1000 / SAMPLE_RATE
        if abs(decoded_ms - metadata["duration_ms"]) > 100:
            raise AudioError(
                f"Decoded duration differs from the container by {abs(decoded_ms - metadata['duration_ms']):.0f} ms."
            )
        samples = np.memmap(raw_path, dtype=np.float32, mode="r", shape=(sample_count,))
        temp_npy = output.with_suffix(".npy.tmp")
        with temp_npy.open("wb") as handle:
            np.save(handle, samples)
        del samples
        os.replace(temp_npy, output)
        result = {
            **metadata,
            "decoded_duration_ms": round(decoded_ms),
            "normalized_sample_rate": SAMPLE_RATE,
            "normalized_samples": sample_count,
            "timeline_offset_ms": round((first_pts or 0) * 1000) - metadata["stream_start_ms"],
            "timestamp_adjustments_samples": adjusted_samples,
            "peaks": peaks,
            "peak_rate": 10,
        }
        atomic_json(output.with_suffix(".json"), result)
        return result
    except av.error.FFmpegError as exc:
        raise AudioError(f"Full decoding failed: {type(exc).__name__}") from exc
    finally:
        raw_path.unlink(missing_ok=True)


def place_on_clock(samples: np.ndarray, delta: int) -> tuple[np.ndarray, int]:
    if delta > 0:
        return np.concatenate((np.zeros(delta, dtype=np.float32), samples)), delta
    if delta < 0:
        trimmed = min(-delta, len(samples))
        return samples[trimmed:], -trimmed
    return samples, 0


def clip_wav(path: Path, start_ms: int, end_ms: int) -> bytes:
    """Decode a short native-rate listening clip without lossy recompression."""
    if start_ms < 0 or end_ms <= start_ms or end_ms - start_ms > 120_000:
        raise AudioError("Choose a clip between 0 and 120 seconds long.")
    payload = io.BytesIO()
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = stream.codec_context.sample_rate
        channels = stream.codec_context.channels
        origin = float((stream.start_time or 0) * stream.time_base)
        container.seek(max(0, int((start_ms / 1000 + origin - 1) / stream.time_base)), stream=stream)
        resampler = av.AudioResampler(format="s16", layout=stream.codec_context.layout, rate=rate)
        with wave.open(payload, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            for frame in container.decode(stream):
                t = float(frame.pts * frame.time_base) - origin if frame.pts is not None else 0
                if t >= end_ms / 1000:
                    break
                for converted in resampler.resample(frame):
                    array = converted.to_ndarray().reshape(-1, channels)
                    left = max(0, round((start_ms / 1000 - t) * rate))
                    right = min(len(array), round((end_ms / 1000 - t) * rate))
                    if right > left:
                        wav.writeframes(array[left:right].tobytes())
    return payload.getvalue()
