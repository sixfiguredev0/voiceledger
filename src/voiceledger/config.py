from __future__ import annotations

import os
from pathlib import Path

# Set before importing either inference library. Downloads are explicit setup operations.
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

MODES = {
    "fast": {"model": "small", "beam_size": 1},
    "balanced": {"model": "large-v3-turbo", "beam_size": 3},
    "accuracy": {"model": "large-v3", "beam_size": 5},
}
ASR_REPOS = {
    "fast": "Systran/faster-whisper-small",
    "balanced": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "accuracy": "Systran/faster-whisper-large-v3",
}
DIARIZATION_REPO = "pyannote/speaker-diarization-community-1"
SAMPLE_RATE = 16000
PIPELINE_VERSION = "1"


def data_root() -> Path:
    override = os.environ.get("VOICELEDGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "VoiceLedger"


def initialize_dirs(root: Path | None = None) -> Path:
    root = root or data_root()
    for name in ("recordings", "artifacts", "models", "exports", "assistant", "backups"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def threads() -> int:
    return max(1, min(int(os.environ.get("VOICELEDGER_THREADS", "8")), os.cpu_count() or 1))
