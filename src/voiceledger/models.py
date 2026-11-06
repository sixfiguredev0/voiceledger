"""Pinned local model storage that does not require Windows symlink privileges."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .audio import atomic_json
from .config import DIARIZATION_REPO


def complete(path: Path, repo: str) -> bool:
    required = (
        [
            "config.yaml",
            "embedding/pytorch_model.bin",
            "segmentation/pytorch_model.bin",
            "plda/plda.npz",
            "plda/xvec_transform.npz",
        ]
        if repo == DIARIZATION_REPO
        else ["config.json", "tokenizer.json", "model.bin"]
    )
    return all((path / name).is_file() and (path / name).stat().st_size > 0 for name in required)


def cached_model(root: Path, repo: str) -> Path:
    from huggingface_hub import snapshot_download

    directory = root / "models" / "local" / repo.replace("/", "--")
    pointer = directory / "active.json"
    if pointer.exists():
        value = json.loads(pointer.read_text(encoding="utf-8"))
        revision = value["revision"]
        if not isinstance(revision, str) or not revision.isalnum():
            raise RuntimeError("The local model registry is invalid.")
        path = directory / revision
        if complete(path, repo):
            return path
    try:
        path = Path(snapshot_download(repo, cache_dir=root / "models", local_files_only=True))
        if complete(path, repo):
            return path
    except Exception:
        pass
    raise RuntimeError(
        f"Model {repo} is not fully downloaded. Use the Models screen or 'voiceledger models' first. "
        "Community-1 also requires accepting its Hugging Face download conditions."
    )


def download_model(root: Path, repo: str) -> Path:
    from huggingface_hub import HfApi, snapshot_download

    try:
        return cached_model(root, repo)
    except RuntimeError:
        pass
    info = HfApi().model_info(repo, files_metadata=True)
    directory = root / "models" / "local" / repo.replace("/", "--")
    target = directory / info.sha
    target.mkdir(parents=True, exist_ok=True)
    # Reuse already downloaded blobs after an interrupted or privilege-limited download.
    # The hub revalidates copied files against the pinned repository metadata.
    legacy = root / "models" / ("models--" + repo.replace("/", "--"))
    for sibling in info.siblings:
        filename = sibling.rfilename
        destination = (target / filename).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise RuntimeError("The model repository contains an invalid path.")
        if destination.exists():
            continue
        lfs = sibling.lfs
        blob = getattr(lfs, "sha256", None) if lfs else None
        if isinstance(lfs, dict):
            blob = lfs.get("sha256")
        blob = blob or sibling.blob_id
        candidates = [legacy / "snapshots" / info.sha / filename]
        if blob:
            candidates.append(legacy / "blobs" / blob)
        for source in candidates:
            if source.is_file() and (sibling.size is None or source.stat().st_size == sibling.size):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                break
    snapshot_download(repo, revision=info.sha, local_dir=target, cache_dir=root / "models")
    if not complete(target, repo):
        raise RuntimeError("The model download is incomplete. Retry to resume it.")
    atomic_json(directory / "active.json", {"repo": repo, "revision": info.sha})
    return target
