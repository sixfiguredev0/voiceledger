"""Isolated, single-stage workers. Workers never write to the project database."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .audio import atomic_json


def execute(task: dict):
    root = Path(task["root"])
    last = 0.0

    def progress(value):
        nonlocal last
        if time.monotonic() - last > 0.25 or value >= 1:
            print(json.dumps({"progress": float(value)}), flush=True)
            last = time.monotonic()

    stage = task["stage"]
    if stage == "normalize":
        from .audio import normalize_audio

        normalize_audio(Path(task["original"]), Path(task["audio"]), progress)
    elif stage == "download":
        from .config import ASR_REPOS, DIARIZATION_REPO
        from .models import download_model

        repos = [ASR_REPOS[task["mode"]], DIARIZATION_REPO]
        for i, repo in enumerate(repos):
            download_model(root, repo)
            progress((i + 1) / len(repos))
    else:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_CACHE"] = str(root / "models")
        from .config import ASR_REPOS, DIARIZATION_REPO
        from .pipeline import cached_model, diarize, reference_embedding, transcribe

        audio = Path(task["audio"])
        region = tuple(task["region"]) if task.get("region") else None
        if stage == "asr":
            transcribe(
                audio,
                cached_model(root, ASR_REPOS[task["mode"]]),
                Path(task["output"]),
                task["mode"],
                task["language"],
                progress,
                region,
            )
        elif stage == "diarization":
            diarize(
                audio,
                cached_model(root, DIARIZATION_REPO),
                root / "models",
                Path(task["output"]),
                progress,
                region,
                task.get("min_speakers"),
                task.get("max_speakers"),
            )
        elif stage == "reference":
            vector = reference_embedding(
                audio, cached_model(root, DIARIZATION_REPO), root / "models", task["start_ms"], task["end_ms"]
            )
            atomic_json(
                Path(task["output"]),
                {"embedding": vector, "model_revision": cached_model(root, DIARIZATION_REPO).name},
            )
        else:
            raise ValueError("Unknown processing stage.")
    progress(1)


if __name__ == "__main__":
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        execute(task)
    except Exception as exc:
        # Full tracebacks remain private; stdout carries a bounded actionable error.
        import traceback

        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:700]}"}), flush=True)
        sys.exit(1)
