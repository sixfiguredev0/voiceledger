from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import psutil
from sqlalchemy import select, update

from .audio import atomic_json, sha256_file
from .config import PIPELINE_VERSION
from .database import Correction, Recording, Run, Sample, now
from .pipeline import align_transcript, artifact_key, model_revisions


class JobCancelled(Exception):
    pass


def terminate_worker(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class JobManager:
    def __init__(self, root: Path, sessions):
        self.root, self.sessions = root, sessions
        self.stop = threading.Event()
        self.thread = None
        self.process = None

    def start(self):
        with self.sessions.begin() as session:
            session.execute(
                update(Run)
                .where(Run.status.in_(["running", "cancelling"]))
                .values(status="interrupted", error="The application stopped. Resume to continue.")
            )
        self.thread = threading.Thread(target=self.loop, daemon=True, name="voiceledger-jobs")
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=15)

    def change(self, run_id, **values):
        with self.sessions.begin() as session:
            session.execute(update(Run).where(Run.id == run_id).values(**values, updated_at=now()))

    def loop(self):
        while not self.stop.is_set():
            with self.sessions() as session:
                run = session.scalar(
                    select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(1)
                )
                run_id = run.id if run else None
            if not run_id:
                self.stop.wait(0.4)
                continue
            try:
                with self.sessions.begin() as session:
                    claimed = session.execute(
                        update(Run)
                        .where(Run.id == run_id, Run.status == "queued")
                        .values(status="running", error=None, updated_at=now())
                    )
                    if claimed.rowcount != 1:
                        continue
                self.execute(run_id)
                self.change(run_id, status="completed", stage="completed", progress=1)
            except JobCancelled:
                self.change(run_id, status="interrupted" if self.stop.is_set() else "cancelled")
            except Exception as exc:
                self.change(run_id, status="failed", error=str(exc)[:1000])

    def stage(self, run_id, name, task, base=0.0, weight=1.0):
        with self.sessions() as session:
            if self.stop.is_set() or session.get(Run, run_id).status != "running":
                raise JobCancelled()
        task = {**task, "root": str(self.root), "stage": name}
        task_dir = self.root / "artifacts" / "jobs" / run_id
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / f"{name}.json"
        atomic_json(task_path, task)
        self.change(run_id, stage=name, progress=base)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYANNOTE_METRICS_ENABLED"] = "0"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        events = queue.Queue()
        peak = 0
        error = None
        with (task_dir / f"{name}.stderr.log").open("w", encoding="utf-8") as stderr:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                [sys.executable, "-m", "voiceledger.worker", str(task_path)],
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                env=env,
                creationflags=flags,
            )
            self.process = process

            def read():
                for line in process.stdout:
                    try:
                        events.put(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                while process.poll() is None or not events.empty():
                    with self.sessions() as session:
                        status = session.get(Run, run_id).status
                    if self.stop.is_set() or status == "cancelling":
                        terminate_worker(process)
                        raise JobCancelled()
                    try:
                        main = psutil.Process(process.pid)
                        memory = sum(p.memory_info().rss for p in [main] + main.children(recursive=True))
                        peak = max(peak, memory)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    try:
                        item = events.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if "progress" in item:
                        self.change(run_id, progress=base + weight * min(1, max(0, item["progress"])))
                    if "error" in item:
                        error = item["error"]
                reader.join(timeout=2)
                if process.wait() != 0:
                    raise RuntimeError(error or f"{name} failed. See the private job diagnostic log.")
            finally:
                self.process = None
        with self.sessions.begin() as session:
            run = session.get(Run, run_id)
            run.details = {**run.details, f"{name}_peak_memory_mib": round(peak / 1024**2, 1)}

    def execute(self, run_id):
        with self.sessions() as session:
            run = session.get(Run, run_id)
            kind, settings, mode, language = run.kind, run.settings, run.mode, run.language
            recording = session.get(Recording, run.recording_id)
        if kind == "download":
            self.stage(run_id, "download", {"mode": mode})
            return
        if not recording:
            raise ValueError("Recording not found.")
        source_dir = self.root / "artifacts" / recording.sha256
        audio = source_dir / "audio.npy"
        if not audio.exists():
            self.stage(
                run_id, "normalize", {"original": recording.original_path, "audio": str(audio)}, 0, 0.08
            )
        if kind == "reference":
            output = source_dir / f"sample-{settings['sample_id']}.json"
            self.stage(
                run_id,
                "reference",
                {
                    "audio": str(audio),
                    "output": str(output),
                    "start_ms": settings["start_ms"],
                    "end_ms": settings["end_ms"],
                },
            )
            with self.sessions.begin() as session:
                sample = session.get(Sample, settings["sample_id"])
                value = json.loads(output.read_text(encoding="utf-8"))
                sample.embedding, sample.model_revision = value["embedding"], value["model_revision"]
            return
        revisions = model_revisions(self.root, mode)
        key = artifact_key(recording.sha256, mode, language, revisions)
        if kind == "reanalyze":
            key += f"-region-{run_id}"
        work = source_dir / key
        work.mkdir(parents=True, exist_ok=True)
        atomic_json(
            work / "manifest.json",
            {
                "source_sha256": recording.sha256,
                "mode": mode,
                "language": language,
                "models": revisions,
                "pipeline_version": PIPELINE_VERSION,
                "settings": settings,
            },
        )
        region = settings.get("region")
        transcript_path = work / "asr" / "transcript.json"
        if region and not transcript_path.exists():
            with self.sessions() as session:
                record = session.get(Recording, recording.id)
                previous = session.get(Run, record.current_run_id) if record.current_run_id else None
                words = (
                    [
                        word
                        for row in previous.raw_rows
                        for word in row.get("words", [])
                        if region[0] <= (word["start_ms"] + word["end_ms"]) / 2 < region[1]
                    ]
                    if previous
                    else []
                )
            if words:
                unique = {(w["start_ms"], w["end_ms"], w["text"]): w for w in words}
                atomic_json(
                    transcript_path,
                    {
                        "words": sorted(unique.values(), key=lambda w: w["start_ms"]),
                        "elapsed_seconds": 0,
                        "cached_sections": 1,
                        "source": "previous_model_transcript",
                        "language": language,
                    },
                )
        if not transcript_path.exists():
            self.stage(
                run_id,
                "asr",
                {
                    "audio": str(audio),
                    "output": str(work / "asr"),
                    "mode": mode,
                    "language": language,
                    "region": region,
                },
                0.08,
                0.47,
            )
        diar_path = (
            work / "diarization.json"
            if region
            else source_dir / f"diarization-{revisions['diarization']}-v{PIPELINE_VERSION}.json"
        )
        if not diar_path.exists():
            self.stage(
                run_id,
                "diarization",
                {
                    "audio": str(audio),
                    "output": str(diar_path),
                    "region": region,
                    "min_speakers": settings.get("min_speakers"),
                    "max_speakers": settings.get("max_speakers"),
                },
                0.55,
                0.44,
            )
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        diar = json.loads(diar_path.read_text(encoding="utf-8"))
        if region:
            # Region-local speaker numbers must never silently replace global identities.
            prefix = f"RECHECK_{run_id[:8]}_"
            for turn in diar["turns"] + diar["exclusive_turns"]:
                turn["cluster"] = prefix + turn["cluster"]
            diar["embeddings"] = {prefix + label: value for label, value in diar["embeddings"].items()}
        rows = align_transcript(recording.id, transcript["words"], diar)
        if sha256_file(Path(recording.original_path)) != recording.sha256:
            raise RuntimeError("The stored original changed. Results were not published.")
        with self.sessions.begin() as session:
            guard = session.execute(
                update(Run).where(Run.id == run_id, Run.status == "running").values(updated_at=now())
            )
            if guard.rowcount != 1 or self.stop.is_set():
                raise JobCancelled()
            if settings.get("correction_id"):
                edit = session.get(Correction, settings["correction_id"])
                if not edit or not edit.active:
                    raise JobCancelled()
            record = session.get(Recording, recording.id)
            latest = session.get(Run, record.current_run_id) if record.current_run_id else None
            if region and latest:
                rows = [
                    r for r in latest.raw_rows if r["end_ms"] <= region[0] or r["start_ms"] >= region[1]
                ] + rows
                rows.sort(key=lambda r: r["start_ms"])
                diar["embeddings"] = {**latest.details.get("embeddings", {}), **diar["embeddings"]}
            current = session.get(Run, run_id)
            current.raw_rows = rows
            current.details = {
                **current.details,
                "models": revisions,
                "embeddings": diar["embeddings"],
                "asr_seconds": transcript["elapsed_seconds"],
                "diarization_seconds": diar["elapsed_seconds"],
            }
            record.current_run_id = run_id
            record.revision += 1
