import json
import shutil
from pathlib import Path

from sqlalchemy import select

from .audio import inspect_audio, normalize_audio, sha256_file
from .database import Project, Recording, Run, Speaker, uid


def demo_directory():
    local = Path(__file__).resolve().parents[2] / "demo"
    return local if (local / "manifest.json").exists() else Path(__file__).parent / "demo"


def load_demo(root, sessions):
    directory = demo_directory()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    with sessions.begin() as session:
        existing = session.scalar(select(Project).where(Project.name == "LibriSpeech review demo"))
        if existing:
            for record in session.scalars(select(Recording).where(Recording.project_id == existing.id)):
                target = root / "artifacts" / record.sha256 / "audio.npy"
                if not target.with_suffix(".json").exists():
                    normalize_audio(Path(record.original_path), target)
            return {"project_id": existing.id}
        project = Project(name="LibriSpeech review demo")
        session.add(project)
        session.flush()
        people = []
        for name in manifest["speakers"]:
            speaker = Speaker(
                project_id=project.id, name=name, notes="Public dataset alias; not an identified real name."
            )
            session.add(speaker)
            session.flush()
            people.append(speaker)
        for item in manifest["recordings"]:
            source = directory / "audio" / item["filename"]
            identifier = uid()
            destination = root / "recordings" / identifier / "original.flac"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            metadata = {**inspect_audio(destination), "demo": True}
            record = Recording(
                id=identifier,
                project_id=project.id,
                filename=item["filename"],
                sha256=sha256_file(destination),
                original_path=str(destination),
                metadata_json=metadata,
            )
            session.add(record)
            session.flush()
            normalize_audio(destination, root / "artifacts" / record.sha256 / "audio.npy")
            rows = []
            for i, turn in enumerate(item["turns"]):
                rows.append(
                    {
                        "id": f"demo-{identifier}-{i}",
                        "recording_id": identifier,
                        "start_ms": turn["start_ms"],
                        "end_ms": turn["end_ms"],
                        "text": turn["text"],
                        "cluster": f"SPEAKER_{turn['speaker']:02d}",
                        "speaker_id": None if turn["uncertain"] else people[turn["speaker"]].id,
                        "words": [],
                        "overlap": False,
                        "uncertain": turn["uncertain"],
                        "excluded": False,
                        "manual": False,
                        "category": "speech",
                    }
                )
            run = Run(
                recording_id=identifier,
                mode="fast",
                status="completed",
                stage="completed",
                progress=1,
                raw_rows=rows,
                details={"demo": True, "source": manifest["source"]},
            )
            session.add(run)
            session.flush()
            record.current_run_id, record.revision = run.id, 1
        return {"project_id": project.id}
