from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import psutil
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select

from . import __version__
from .audio import clip_wav, inspect_audio, sha256_file
from .config import ASR_REPOS, DIARIZATION_REPO, initialize_dirs
from .corrections import (
    Conflict,
    apply_proposal,
    canonical_speaker,
    effective_rows,
    preview,
    speaker_redirects,
    undo_correction,
)
from .database import Correction, Project, Proposal, Recording, Run, Sample, Speaker, database, serialize, uid
from .exports import export_recordings
from .jobs import JobManager
from .schemas import AssistantRequest, JobRequest, PreviewRequest


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SampleInput(BaseModel):
    recording_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confirmed: bool


class HuggingFaceLogin(BaseModel):
    token: SecretStr


def create_app(root: Path | None = None, *, start_worker=True, frontend: Path | None = None):
    root = initialize_dirs(root)
    sessions, engine = database(root)
    manager = JobManager(root, sessions)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        from filelock import FileLock

        lock = FileLock(root / "voiceledger.lock")
        if start_worker:
            lock.acquire(timeout=0)
            manager.start()
        try:
            yield
        finally:
            manager.close()
            if start_worker:
                lock.release()
            engine.dispose()

    app = FastAPI(title="VoiceLedger", version=__version__, lifespan=lifespan)
    app.state.sessions, app.state.root, app.state.manager = sessions, root, manager

    @app.middleware("http")
    async def local_session(request: Request, call_next):
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse(
                {"detail": "VoiceLedger accepts localhost connections only."}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin access is disabled."}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/v1/session":
            supplied = request.headers.get("x-voiceledger-token") or request.cookies.get(
                "voiceledger_session", ""
            )
            if not secrets.compare_digest(supplied, token):
                return JSONResponse(
                    {"detail": "Open VoiceLedger to initialize this local session."}, status_code=401
                )
            if request.method not in ("GET", "HEAD") and request.headers.get("x-voiceledger-token") != token:
                return JSONResponse({"detail": "A local session token is required."}, status_code=403)
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Conflict) else 400)

    def get_record(session, identifier):
        record = session.get(Recording, identifier)
        if not record:
            raise HTTPException(404, "Recording not found.")
        return record

    def record_json(record):
        return serialize(record, ("original_path",))

    def job_json(run):
        value = serialize(run, ("raw_rows",))
        value["details"] = {k: v for k, v in value["details"].items() if k != "embeddings"}
        return value

    @app.get("/api/v1/session")
    def session_init():
        response = JSONResponse({"token": token, "version": __version__})
        response.set_cookie("voiceledger_session", token, httponly=True, samesite="strict")
        return response

    @app.get("/api/v1/health")
    def health():
        return {
            "version": __version__,
            "available_ram_gib": round(psutil.virtual_memory().available / 1024**3, 1),
            "disk_free_gib": round(shutil.disk_usage(root).free / 1024**3, 1),
            "cpu_only": True,
        }

    @app.post("/api/v1/demo")
    def demo():
        from .demo import load_demo

        return load_demo(root, sessions)

    @app.get("/api/v1/projects")
    def projects():
        with sessions() as session:
            return [serialize(p) for p in session.scalars(select(Project).order_by(Project.created_at))]

    @app.get("/api/v1/huggingface/status")
    def hf_status():
        from huggingface_hub import get_token

        return {"signed_in": bool(get_token())}

    @app.post("/api/v1/huggingface/login")
    async def hf_login(value: HuggingFaceLogin):
        from huggingface_hub import login

        try:
            await asyncio.to_thread(login, token=value.token.get_secret_value(), add_to_git_credential=False)
        except Exception:
            raise ValueError(
                "Hugging Face could not validate this token. Use a read token with Community-1 access."
            )
        return {"signed_in": True}

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page():
        return (Path(__file__).parent / "setup.html").read_text(encoding="utf-8")

    @app.post("/api/v1/projects")
    def new_project(value: ProjectInput):
        with sessions.begin() as session:
            project = Project(name=value.name.strip())
            session.add(project)
            session.flush()
            return serialize(project)

    @app.get("/api/v1/projects/{project_id}/recordings")
    def recordings(project_id: str):
        with sessions() as session:
            return [
                record_json(r)
                for r in session.scalars(
                    select(Recording).where(Recording.project_id == project_id).order_by(Recording.created_at)
                )
            ]

    @app.post("/api/v1/projects/{project_id}/recordings")
    async def upload(project_id: str, file: UploadFile = File(...)):
        with sessions() as session:
            if not session.get(Project, project_id):
                raise HTTPException(404, "Project not found.")
        identifier = uid()
        destination = root / "recordings" / identifier
        destination.mkdir()
        filename = Path((file.filename or "recording").replace("\\", "/")).name
        path = destination / ("original" + Path(filename).suffix.lower())
        digest, written = hashlib.sha256(), 0
        try:
            with path.open("xb") as handle:
                while block := await file.read(1024 * 1024):
                    written += len(block)
                    if written > 8 * 1024**3:
                        raise ValueError("The maximum file size is 8 GiB.")
                    handle.write(block)
                    digest.update(block)
            metadata = await asyncio.to_thread(inspect_audio, path)
            if await asyncio.to_thread(sha256_file, path) != digest.hexdigest():
                raise ValueError("The imported file failed its integrity check.")
            with sessions.begin() as session:
                record = Recording(
                    id=identifier,
                    project_id=project_id,
                    filename=filename,
                    sha256=digest.hexdigest(),
                    original_path=str(path),
                    metadata_json=metadata,
                )
                session.add(record)
                session.flush()
                return record_json(record)
        except Exception:
            path.unlink(missing_ok=True)
            destination.rmdir()
            raise
        finally:
            await file.close()

    @app.get("/api/v1/recordings/{recording_id}/transcript")
    def transcript(
        recording_id: str,
        offset: int = 0,
        limit: int = 500,
        search: str = "",
        speaker_id: str | None = None,
        uncertain: bool = False,
        excluded: bool = True,
    ):
        with sessions() as session:
            record = get_record(session, recording_id)
            rows, conflicts = effective_rows(session, record)
            if search:
                rows = [r for r in rows if search.casefold() in r["text"].casefold()]
            if speaker_id:
                rows = [r for r in rows if r["speaker_id"] == speaker_id or r["cluster"] == speaker_id]
            if uncertain:
                rows = [r for r in rows if r["uncertain"]]
            if not excluded:
                rows = [r for r in rows if not r["excluded"]]
            return {
                "revision": record.revision,
                "total": len(rows),
                "conflicts": conflicts,
                "rows": rows[max(0, offset) : max(0, offset) + min(2000, max(1, limit))],
            }

    @app.get("/api/v1/recordings/{recording_id}/audio")
    def audio(recording_id: str):
        with sessions() as session:
            record = get_record(session, recording_id)
            return FileResponse(
                record.original_path,
                filename=record.filename,
                media_type="audio/mp4" if record.filename.lower().endswith(".m4a") else None,
                content_disposition_type="inline",
            )

    @app.get("/api/v1/recordings/{recording_id}/clip")
    def clip(recording_id: str, start_ms: int, end_ms: int):
        with sessions() as session:
            record = get_record(session, recording_id)
            if end_ms > record.metadata_json["duration_ms"]:
                raise ValueError("The clip extends past the end of the recording.")
            return Response(clip_wav(Path(record.original_path), start_ms, end_ms), media_type="audio/wav")

    @app.get("/api/v1/recordings/{recording_id}/peaks")
    def peaks(recording_id: str):
        with sessions() as session:
            record = get_record(session, recording_id)
            path = root / "artifacts" / record.sha256 / "audio.json"
            if not path.exists():
                return {"peaks": [], "duration": record.metadata_json["duration_ms"] / 1000}
            value = json.loads(path.read_text(encoding="utf-8"))
            return {"peaks": value["peaks"], "duration": record.metadata_json["duration_ms"] / 1000}

    @app.post("/api/v1/jobs")
    def start_job(value: JobRequest):
        from .pipeline import model_revisions

        model_revisions(root, value.mode)
        with sessions.begin() as session:
            get_record(session, value.recording_id)
            active = session.scalar(
                select(Run).where(
                    Run.recording_id == value.recording_id,
                    Run.status.in_(["queued", "running", "cancelling"]),
                )
            )
            if active:
                raise Conflict("A job for this recording is already queued or running.")
            run = Run(recording_id=value.recording_id, mode=value.mode, language=value.language)
            session.add(run)
            session.flush()
            return serialize(run, ("raw_rows",))

    @app.get("/api/v1/jobs")
    def jobs():
        with sessions() as session:
            return [
                job_json(run)
                for run in session.scalars(select(Run).order_by(Run.created_at.desc()).limit(100))
            ]

    @app.post("/api/v1/jobs/{run_id}/{operation}")
    def job_operation(run_id: str, operation: str):
        with sessions.begin() as session:
            run = session.get(Run, run_id)
            if not run:
                raise HTTPException(404, "Job not found.")
            if operation == "cancel" and run.status in ("queued", "running"):
                run.status = "cancelled" if run.status == "queued" else "cancelling"
            elif operation == "resume" and run.status in ("cancelled", "interrupted", "failed"):
                if run.settings.get("correction_id"):
                    edit = session.get(Correction, run.settings["correction_id"])
                    if not edit or not edit.active:
                        raise ValueError("This recheck was undone. Create a new speaker recheck instead.")
                run.status, run.error = "queued", None
            else:
                raise ValueError("This operation is not available for the job's current state.")
            return serialize(run, ("raw_rows",))

    @app.get("/api/v1/jobs/{run_id}/events")
    def events(run_id: str):
        async def stream():
            previous = None
            while True:
                with sessions() as session:
                    run = session.get(Run, run_id)
                    if not run:
                        return
                    value = job_json(run)
                encoded = json.dumps(value)
                if encoded != previous:
                    yield f"data: {encoded}\n\n"
                    previous = encoded
                if value["status"] in ("completed", "failed", "cancelled", "interrupted"):
                    return
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/v1/models")
    def models():
        from .pipeline import cached_model

        result = {}
        for name, repo in {**ASR_REPOS, "diarization": DIARIZATION_REPO}.items():
            try:
                path = cached_model(root, repo)
                ready = (
                    (path / "model.bin").exists()
                    if name != "diarization"
                    else (path / "config.yaml").exists()
                )
                result[name] = {"ready": ready, "revision": path.name}
            except RuntimeError:
                result[name] = {"ready": False, "revision": None}
        return result

    @app.post("/api/v1/models/{mode}/download")
    def download(mode: str):
        if mode not in ASR_REPOS:
            raise ValueError("Unknown processing mode.")
        with sessions.begin() as session:
            run = Run(recording_id="setup", mode=mode, kind="download")
            session.add(run)
            session.flush()
            return serialize(run, ("raw_rows",))

    @app.get("/api/v1/projects/{project_id}/speakers")
    def speakers(project_id: str):
        with sessions() as session:
            result = []
            redirects = speaker_redirects(session, project_id)
            for speaker in session.scalars(select(Speaker).where(Speaker.project_id == project_id)):
                if canonical_speaker(speaker.id, redirects) != speaker.id:
                    continue
                grouped = [
                    s.id
                    for s in session.scalars(select(Speaker).where(Speaker.project_id == project_id))
                    if canonical_speaker(s.id, redirects) == speaker.id
                ]
                samples = session.scalars(select(Sample).where(Sample.speaker_id.in_(grouped))).all()
                result.append(
                    {**serialize(speaker), "samples": [serialize(s, ("embedding",)) for s in samples]}
                )
            return result

    @app.post("/api/v1/speakers/{speaker_id}/samples")
    def add_sample(speaker_id: str, value: SampleInput):
        with sessions.begin() as session:
            record = get_record(session, value.recording_id)
            speaker = session.get(Speaker, speaker_id)
            if not speaker or speaker.project_id != record.project_id:
                raise ValueError("Speaker not found in this project.")
            if not value.confirmed or not 1000 <= value.end_ms - value.start_ms <= 120000:
                raise ValueError("Confirm a clean single-speaker clip of 1–120 seconds.")
            if value.end_ms > record.metadata_json["duration_ms"]:
                raise ValueError("The reference clip extends past the recording.")
            rows, _ = effective_rows(session, record)
            overlaps = [r for r in rows if r["end_ms"] > value.start_ms and r["start_ms"] < value.end_ms]
            if any(r["overlap"] or r["excluded"] for r in overlaps):
                raise ValueError("Choose a clip without flagged overlap, noise or excluded speech.")
            sample = Sample(
                speaker_id=speaker_id, recording_id=record.id, start_ms=value.start_ms, end_ms=value.end_ms
            )
            session.add(sample)
            session.flush()
            run = Run(
                recording_id=record.id,
                mode="fast",
                kind="reference",
                settings={"sample_id": sample.id, "start_ms": value.start_ms, "end_ms": value.end_ms},
            )
            session.add(run)
            return {"sample_id": sample.id}

    @app.get("/api/v1/recordings/{recording_id}/matches")
    def matches(recording_id: str):
        with sessions() as session:
            record = get_record(session, recording_id)
            run = session.get(Run, record.current_run_id) if record.current_run_id else None
            if not run:
                return []
            revision = run.details.get("models", {}).get("diarization")
            result = []
            for cluster, embedding in run.details.get("embeddings", {}).items():
                vector = np.array(embedding)
                if not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
                    continue
                candidates = []
                for speaker in session.scalars(
                    select(Speaker).where(Speaker.project_id == record.project_id)
                ):
                    redirects = speaker_redirects(session, record.project_id)
                    if canonical_speaker(speaker.id, redirects) != speaker.id:
                        continue
                    grouped = [
                        s.id
                        for s in session.scalars(
                            select(Speaker).where(Speaker.project_id == record.project_id)
                        )
                        if canonical_speaker(s.id, redirects) == speaker.id
                    ]
                    refs = session.scalars(
                        select(Sample).where(
                            Sample.speaker_id.in_(grouped), Sample.model_revision == revision
                        )
                    ).all()
                    refs = [
                        s
                        for s in refs
                        if len(s.embedding) == len(vector)
                        and np.isfinite(s.embedding).all()
                        and np.linalg.norm(s.embedding) >= 1e-8
                    ]
                    vectors = [s.embedding for s in refs]
                    if not vectors:
                        continue
                    template = np.mean(vectors, axis=0)
                    if np.linalg.norm(template) < 1e-8:
                        continue
                    score = float(
                        np.dot(vector / np.linalg.norm(vector), template / np.linalg.norm(template))
                    )
                    candidates.append(
                        {
                            "speaker_id": speaker.id,
                            "name": speaker.name,
                            "similarity": round(score, 4),
                            "sample_id": refs[0].id,
                            "recording_id": refs[0].recording_id,
                            "start_ms": refs[0].start_ms,
                            "end_ms": refs[0].end_ms,
                        }
                    )
                result.append(
                    {"cluster": cluster, "candidates": sorted(candidates, key=lambda c: -c["similarity"])[:3]}
                )
            return result

    @app.post("/api/v1/corrections/preview")
    def correction_preview(value: PreviewRequest):
        with sessions() as session:
            record = get_record(session, value.recording_id)
            return preview(session, record, value.base_revision, value.actions)

    @app.post("/api/v1/proposals/{proposal_id}/apply")
    def correction_apply(proposal_id: str):
        with sessions() as session:
            proposal = session.get(Proposal, proposal_id)
            if not proposal:
                raise HTTPException(404, "Proposal not found.")
            correction = apply_proposal(session, proposal)
            return serialize(correction)

    @app.get("/api/v1/recordings/{recording_id}/corrections")
    def history(recording_id: str):
        with sessions() as session:
            get_record(session, recording_id)
            return [
                serialize(c)
                for c in session.scalars(
                    select(Correction)
                    .where(Correction.recording_id == recording_id)
                    .order_by(Correction.created_at.desc())
                )
            ]

    @app.post("/api/v1/corrections/{correction_id}/undo")
    def undo(correction_id: str):
        with sessions.begin() as session:
            edit = session.get(Correction, correction_id)
            return {"revision": undo_correction(session, edit)}

    @app.get("/api/v1/assistant/status")
    def assistant_status():
        from .assistant import codex_status

        return codex_status()

    @app.post("/api/v1/assistant/preview")
    async def assistant_preview(value: AssistantRequest):
        from .assistant import interpret

        with sessions() as session:
            record = get_record(session, value.recording_id)
            if record.revision != value.base_revision:
                raise Conflict("Refresh the transcript before requesting a correction.")
            rows, _ = effective_rows(session, record)
            chosen = [r for r in rows if r["id"] in value.row_ids]
            if len(chosen) != len(set(value.row_ids)):
                raise ValueError("A selected turn no longer exists.")
            context = {
                "selection": [
                    {k: r[k] for k in ("id", "start_ms", "end_ms", "cluster", "speaker_id")} for r in chosen
                ],
                "speakers": [
                    {"id": s.id, "name": s.name}
                    for s in session.scalars(select(Speaker).where(Speaker.project_id == record.project_id))
                ],
            }
        result = await asyncio.to_thread(interpret, root / "assistant", value.instruction, context)
        with sessions() as session:
            record = get_record(session, value.recording_id)
            if result.clarification or not result.actions:
                return {
                    "clarification": result.clarification or result.explanation,
                    "actions": [],
                    "explanation": result.explanation,
                }
            return preview(session, record, value.base_revision, result.actions, result.explanation)

    @app.get("/api/v1/projects/{project_id}/export/{format}")
    def export(project_id: str, format: str, recording_id: str | None = None, include_excluded: bool = False):
        with sessions() as session:
            query = select(Recording).where(Recording.project_id == project_id).order_by(Recording.created_at)
            if recording_id:
                query = query.where(Recording.id == recording_id)
            groups = []
            for record in session.scalars(query):
                rows, _ = effective_rows(session, record)
                groups.append(
                    {
                        "id": record.id,
                        "filename": record.filename,
                        "duration_ms": record.metadata_json["duration_ms"],
                        "turns": rows,
                    }
                )
            names = {
                s.id: s.name for s in session.scalars(select(Speaker).where(Speaker.project_id == project_id))
            }
            payload, mime = export_recordings(groups, names, format, include_excluded)
            return Response(
                payload,
                media_type=mime,
                headers={"Content-Disposition": f'attachment; filename="voiceledger.{format}"'},
            )

    if frontend is None:
        candidate = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        frontend = candidate if candidate.exists() else Path(__file__).parent / "web"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="interface")
    else:

        @app.get("/")
        def no_frontend():
            return {
                "message": "Build the interface with npm --prefix frontend run build, then reopen VoiceLedger."
            }

    return app
