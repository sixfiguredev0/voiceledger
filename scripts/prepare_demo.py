"""Create a small attributed demo from the official LibriSpeech test-clean archive.

The supplied source transcripts and speaker IDs are ground truth, not model output.
The application deliberately leaves two turns unconfirmed to demonstrate review.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    archive = ROOT / ".cache" / "demo" / "test-clean.tar.gz"
    output = ROOT / "demo"
    (output / "audio").mkdir(parents=True, exist_ok=True)
    selected = {}
    transcripts = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            parts = member.name.split("/")
            if len(parts) != 5 or parts[0] != "LibriSpeech":
                continue
            speaker = parts[2]
            if speaker not in selected and len(selected) < 3:
                selected[speaker] = []
            if speaker not in selected:
                continue
            handle = tar.extractfile(member) if member.isfile() else None
            if handle is None:
                continue
            if member.name.endswith(".trans.txt"):
                for line in handle.read().decode().splitlines():
                    identifier, text = line.split(" ", 1)
                    transcripts[identifier] = text
            elif member.name.endswith(".flac") and len(selected[speaker]) < 3:
                payload = handle.read()
                with av.open(io.BytesIO(payload)) as container:
                    chunks = [frame.to_ndarray().reshape(-1) for frame in container.decode(audio=0)]
                samples = np.concatenate(chunks).astype(np.int16)
                if 3 * 16000 <= len(samples) <= 25 * 16000:
                    selected[speaker].append(
                        {"source": member.name, "id": Path(member.name).stem, "audio": samples}
                    )
    chosen = [items for items in selected.values() if len(items) >= 3]
    if len(chosen) != 3:
        raise RuntimeError("The archive did not contain the expected three speakers.")
    sessions = [((0, 0), (1, 0), (2, 0), (0, 1)), ((1, 1), (0, 2), (2, 1), (1, 2))]
    records = []
    sources = []
    for index, sequence in enumerate(sessions):
        cursor, audio, turns = 0, [], []
        for turn_index, (speaker, utterance) in enumerate(sequence):
            source = chosen[speaker][utterance]
            samples = source["audio"]
            start = round(cursor * 1000 / 16000)
            audio.append(samples)
            cursor += len(samples)
            end = round(cursor * 1000 / 16000)
            turns.append(
                {
                    "start_ms": start,
                    "end_ms": end,
                    "speaker": speaker,
                    "text": transcripts[source["id"]],
                    "uncertain": turn_index == 2,
                }
            )
            sources.append(source["source"])
            audio.append(np.zeros(4000, dtype=np.int16))
            cursor += 4000
        pcm = np.concatenate(audio)
        filename = f"session-{index + 1}.flac"
        with av.open(str(output / "audio" / filename), "w", format="flac") as container:
            stream = container.add_stream("flac", rate=16000)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(pcm[None, :], format="s16", layout="mono")
            frame.sample_rate = 16000
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        records.append({"filename": filename, "turns": turns})
    manifest = {
        "title": "LibriSpeech review demo",
        "license": "CC-BY-4.0",
        "source": "https://www.openslr.org/12",
        "archive": "test-clean.tar.gz",
        "creators": "Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur",
        "description": "A curated sequence of English audiobook excerpts, not a recorded conversation. "
        "Transcripts and speaker groupings come from the source dataset. "
        "Two turns are deliberately unconfirmed to demonstrate review. No model accuracy is implied.",
        "modifications": "Selected utterances concatenated with 250 ms silence; encoded to lossless FLAC.",
        "source_files": sources,
        "speakers": ["Reader A", "Reader B", "Reader C"],
        "recordings": records,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Prepared {len(records)} public demo recordings, {sum((output / 'audio' / r['filename']).stat().st_size for r in records)} bytes."
    )


if __name__ == "__main__":
    main()
