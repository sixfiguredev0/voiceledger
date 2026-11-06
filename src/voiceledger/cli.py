from __future__ import annotations

import importlib.metadata
import json
import shutil
from pathlib import Path

import psutil
import typer

from .config import ASR_REPOS, DIARIZATION_REPO, data_root, initialize_dirs

app = typer.Typer(
    no_args_is_help=True, help="Local transcription and speaker review.", pretty_exceptions_show_locals=False
)


@app.command()
def doctor():
    """Inspect this installation without sending recordings anywhere."""
    from huggingface_hub import get_token

    from .assistant import find_codex

    report = {
        "python": __import__("sys").version.split()[0],
        "cpu_threads": psutil.cpu_count(),
        "ram_gib": round(psutil.virtual_memory().total / 1024**3, 1),
        "available_ram_gib": round(psutil.virtual_memory().available / 1024**3, 1),
        "disk_free_gib": round(shutil.disk_usage(Path.cwd()).free / 1024**3, 1),
        "data_directory": str(data_root()),
        "huggingface_login_available": bool(get_token()),
        "codex_available": bool(find_codex()),
        "packages": {},
    }
    for package in ("av", "torch", "torchaudio", "torchcodec", "faster-whisper", "pyannote.audio"):
        try:
            report["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][package] = "missing"
    typer.echo(json.dumps(report, indent=2))


@app.command()
def inspect(path: Path, decode: bool = False, output: Path | None = None):
    """Read metadata and optionally verify complete decoding to private working audio."""
    from .audio import inspect_audio, normalize_audio, sha256_file

    paths = sorted(path.glob("*.m4a")) if path.is_dir() else [path]
    root = initialize_dirs(output)
    results = []
    for source in paths:
        digest = sha256_file(source)
        target = root / "artifacts" / digest / "audio.npy"
        result = normalize_audio(source, target) if decode else inspect_audio(source)
        result.pop("peaks", None)
        results.append({"file": source.name, "sha256": digest, **result})
    typer.echo(json.dumps(results, ensure_ascii=False, indent=2))


@app.command("models")
def download_models(mode: str = "balanced", diarization: bool = True):
    """Explicitly download free models. Accept Community-1 conditions on Hugging Face first."""
    from .models import download_model

    if mode not in ASR_REPOS:
        raise typer.BadParameter("Mode must be fast, balanced or accuracy.")
    root = initialize_dirs()
    for repo in [ASR_REPOS[mode]] + ([DIARIZATION_REPO] if diarization else []):
        typer.echo(f"Downloading {repo}")
        download_model(root, repo)
    typer.echo("Models downloaded. Processing can use the local cache.")


@app.command()
def login():
    """Authenticate to Hugging Face using its local hidden token prompt."""
    from huggingface_hub import login as hf_login

    hf_login(add_to_git_credential=False)


@app.command()
def benchmark(
    path: Path,
    mode: str = "fast",
    start: float = 60,
    seconds: float = 60,
    diarization: bool = True,
    output: Path | None = None,
):
    """Measure a private excerpt. This reports timing and counts, never transcript content."""
    import time

    from .audio import atomic_json, clip_wav, normalize_audio
    from .pipeline import cached_model, diarize, transcribe

    if mode not in ASR_REPOS or start < 0 or not 1 <= seconds <= 120:
        raise typer.BadParameter("Choose a valid mode and a clip of 1–120 seconds.")
    root = initialize_dirs()
    target = output or root / "artifacts" / "benchmark"
    target.mkdir(parents=True, exist_ok=True)
    clip = target / "excerpt.wav"
    clip.write_bytes(clip_wav(path, round(start * 1000), round((start + seconds) * 1000)))
    audio = target / "audio.npy"
    normalize_audio(clip, audio)
    t = time.perf_counter()
    transcript = transcribe(audio, cached_model(root, ASR_REPOS[mode]), target / mode, mode)
    report = {
        "mode": mode,
        "excerpt_seconds": seconds,
        "asr_seconds": round(time.perf_counter() - t, 2),
        "words": len(transcript["words"]),
        "cached_sections": transcript["cached_sections"],
        "quality_evaluated": False,
    }
    if diarization:
        t = time.perf_counter()
        diar = diarize(
            audio,
            cached_model(root, DIARIZATION_REPO),
            root / "models",
            target / "diarization.json",
            progress=lambda value: typer.echo(f"Speaker analysis: {round(value * 100)}%", err=True),
        )
        report.update(diarization_seconds=round(time.perf_counter() - t, 2), speakers=len(diar["embeddings"]))
    atomic_json(target / f"benchmark-{mode}.json", report)
    typer.echo(json.dumps(report, indent=2))


@app.command()
def launch(port: int = 8020, open_browser: bool = True):
    """Open the local review application. The service only listens on this computer."""
    import threading
    import webbrowser

    import uvicorn

    from .api import create_app

    if not 1024 <= port <= 65535:
        raise typer.BadParameter("Choose a port between 1024 and 65535.")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, workers=1)


@app.command("evaluate")
def evaluate_reference(
    recording_id: str,
    reference: Path,
    speaker_map: Path | None = None,
    start: float = 0,
    seconds: float = 180,
):
    """Compare immutable model output with a manually reviewed JSON export; print metrics only."""
    from .database import Recording, Run, database
    from .evaluation import evaluate

    if start < 0 or seconds <= 0:
        raise typer.BadParameter("Choose a non-negative start and a positive duration.")
    supplied = json.loads(reference.read_text(encoding="utf-8"))
    reviewed = next((r for r in supplied["recordings"] if r["id"] == recording_id), None)
    if reviewed is None:
        raise typer.BadParameter("The reference export does not contain this recording ID.")
    mapping = json.loads(speaker_map.read_text(encoding="utf-8")) if speaker_map else {}
    sessions, engine = database(initialize_dirs())
    try:
        with sessions() as session:
            record = session.get(Recording, recording_id)
            run = session.get(Run, record.current_run_id) if record and record.current_run_id else None
            if run is None:
                raise typer.BadParameter("This recording has no completed model output.")
            report = evaluate(
                run.raw_rows,
                reviewed["turns"],
                supplied["speakers"],
                mapping,
                round(start * 1000),
                round((start + seconds) * 1000),
            )
        typer.echo(json.dumps(report, indent=2, ensure_ascii=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    app()
