import io
import wave

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from voiceledger.api import create_app
from voiceledger.database import Recording, Run, Speaker


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        value = client.get("/api/v1/session").json()
        client.headers["x-voiceledger-token"] = value["token"]
        yield client


def seed(client):
    project = client.post("/api/v1/projects", json={"name": "Тест"}).json()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0" * 16000 * 4)
    response = client.post(
        f"/api/v1/projects/{project['id']}/recordings",
        files={"file": ("sample.wav", buffer.getvalue(), "audio/wav")},
    )
    assert response.status_code == 200, response.text
    record = response.json()
    rows = [
        {
            "id": "turn-1",
            "recording_id": record["id"],
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Здравей свят",
            "cluster": "A",
            "speaker_id": None,
            "overlap": False,
            "uncertain": False,
            "excluded": False,
            "manual": False,
            "category": "speech",
            "words": [
                {"start_ms": 0, "end_ms": 400, "text": "Здравей"},
                {"start_ms": 500, "end_ms": 1000, "text": " свят"},
            ],
        }
    ]
    with client.app.state.sessions.begin() as session:
        run = Run(recording_id=record["id"], mode="fast", status="completed", raw_rows=rows)
        session.add(run)
        session.flush()
        obj = session.get(Recording, record["id"])
        obj.current_run_id, obj.revision = run.id, 1
    return project, record


def test_local_origin_and_session_required(client):
    assert (
        client.post(
            "/api/v1/projects", json={"name": "bad"}, headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/health", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/v1/health").status_code == 200


def test_corrections_stale_proposals_exports_and_undo(client):
    project, record = seed(client)
    route = f"/api/v1/recordings/{record['id']}/transcript"
    assert client.get(route).json()["rows"][0]["text"] == "Здравей свят"
    value = {
        "recording_id": record["id"],
        "base_revision": 1,
        "actions": [{"kind": "assign", "row_ids": ["turn-1"], "name": "Ясен"}],
    }
    p1 = client.post("/api/v1/corrections/preview", json=value)
    assert p1.status_code == 200, p1.text
    p2 = client.post("/api/v1/corrections/preview", json=value).json()
    applied = client.post(f"/api/v1/proposals/{p1.json()['id']}/apply")
    assert applied.status_code == 200, applied.text
    assert client.post(f"/api/v1/proposals/{p2['id']}/apply").status_code == 409
    rows = client.get(route).json()
    assert rows["revision"] == 2 and rows["rows"][0]["speaker_id"]
    exported = client.get(f"/api/v1/projects/{project['id']}/export/json").json()
    assert "Ясен" in exported["speakers"].values()
    assert "original_path" not in str(exported)
    assert client.post(f"/api/v1/corrections/{applied.json()['id']}/undo").status_code == 200
    assert client.get(route).json()["rows"][0]["speaker_id"] is None


def test_split_exclusion_reanalysis_conflicts_and_audio_ranges(client):
    project, record = seed(client)
    preview = client.post(
        "/api/v1/corrections/preview",
        json={
            "recording_id": record["id"],
            "base_revision": 1,
            "actions": [{"kind": "split", "row_ids": ["turn-1"], "split_at_ms": 450}],
        },
    ).json()
    assert client.post(f"/api/v1/proposals/{preview['id']}/apply").status_code == 200
    transcript = client.get(f"/api/v1/recordings/{record['id']}/transcript").json()
    assert [r["text"] for r in transcript["rows"]] == ["Здравей", "свят"]
    invalid = client.post(
        "/api/v1/corrections/preview",
        json={
            "recording_id": record["id"],
            "base_revision": 2,
            "actions": [{"kind": "mark", "row_ids": ["missing"], "category": "noise"}],
        },
    )
    assert invalid.status_code == 409
    with client.app.state.sessions.begin() as session:
        obj = session.get(Recording, record["id"])
        run = session.get(Run, obj.current_run_id)
        run.raw_rows = [{**run.raw_rows[0], "id": "new-boundaries"}]
        obj.revision += 1
    assert client.get(f"/api/v1/recordings/{record['id']}/transcript").json()["conflicts"]
    audio = client.get(f"/api/v1/recordings/{record['id']}/audio", headers={"range": "bytes=0-99"})
    assert audio.status_code == 206 and len(audio.content) == 100


def test_upload_rejects_invalid_audio(client):
    project = client.post("/api/v1/projects", json={"name": "demo"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/recordings", files={"file": ("bad.m4a", b"not audio", "audio/mp4")}
    )
    assert response.status_code == 400
    assert not list((client.app.state.root / "recordings").iterdir())


def recheck(client, record):
    proposal = client.post(
        "/api/v1/corrections/preview",
        json={
            "recording_id": record["id"],
            "base_revision": 1,
            "actions": [
                {
                    "kind": "reanalyze",
                    "row_ids": ["turn-1"],
                    "start_ms": 100,
                    "end_ms": 900,
                    "min_speakers": 3,
                }
            ],
        },
    )
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["actions"][0]["start_ms"] == 0
    applied = client.post(f"/api/v1/proposals/{proposal.json()['id']}/apply")
    assert applied.status_code == 200, applied.text
    with client.app.state.sessions() as session:
        run = session.scalar(select(Run).where(Run.kind == "reanalyze"))
        assert run.settings["correction_id"] == applied.json()["id"]
        assert run.settings["previous_run_id"]
        return applied.json(), run.id, run.settings["previous_run_id"]


def test_undo_queued_recheck_cancels_it_and_prevents_resume(client):
    _, record = seed(client)
    edit, run_id, _ = recheck(client, record)
    assert client.post(f"/api/v1/corrections/{edit['id']}/undo").status_code == 200
    with client.app.state.sessions() as session:
        assert session.get(Run, run_id).status == "cancelled"
    assert client.post(f"/api/v1/jobs/{run_id}/resume").status_code == 400


def test_undo_completed_recheck_restores_original_analysis(client):
    _, record = seed(client)
    edit, run_id, previous_id = recheck(client, record)
    with client.app.state.sessions.begin() as session:
        run = session.get(Run, run_id)
        run.status, run.raw_rows = "completed", []
        obj = session.get(Recording, record["id"])
        obj.current_run_id, obj.revision = run.id, obj.revision + 1
    assert client.post(f"/api/v1/corrections/{edit['id']}/undo").status_code == 200
    with client.app.state.sessions() as session:
        assert session.get(Recording, record["id"]).current_run_id == previous_id
    assert (
        client.get(f"/api/v1/recordings/{record['id']}/transcript").json()["rows"][0]["text"]
        == "Здравей свят"
    )


def test_merge_cycle_rejected_and_merge_undo_restores_both_recordings(client):
    project, record = seed(client)
    with client.app.state.sessions.begin() as session:
        people = [Speaker(project_id=project["id"], name=name) for name in ("Alice", "Bob")]
        session.add_all(people)
        session.flush()
        a, b = [person.id for person in people]
        first = session.get(Recording, record["id"])
        raw = session.get(Run, first.current_run_id)
        raw.raw_rows = [{**raw.raw_rows[0], "speaker_id": a}]
        second = Recording(
            project_id=project["id"],
            filename="second.wav",
            sha256=first.sha256,
            original_path=first.original_path,
            metadata_json=first.metadata_json,
        )
        session.add(second)
        session.flush()
        second_run = Run(recording_id=second.id, mode="fast", status="completed", raw_rows=raw.raw_rows)
        session.add(second_run)
        session.flush()
        second.current_run_id, second.revision = second_run.id, 1
        other_id = second.id
    forward = {"kind": "merge", "source_speaker_id": a, "speaker_id": b}
    backward = {"kind": "merge", "source_speaker_id": b, "speaker_id": a}
    invalid = client.post(
        "/api/v1/corrections/preview",
        json={"recording_id": record["id"], "base_revision": 1, "actions": [forward, backward]},
    )
    assert invalid.status_code == 400
    proposal = client.post(
        "/api/v1/corrections/preview",
        json={"recording_id": record["id"], "base_revision": 1, "actions": [forward]},
    ).json()
    assert proposal["affected_turns"] == 2
    edit = client.post(f"/api/v1/proposals/{proposal['id']}/apply").json()
    for identifier in (record["id"], other_id):
        data = client.get(f"/api/v1/recordings/{identifier}/transcript").json()
        assert data["revision"] == 2 and data["rows"][0]["speaker_id"] == b
    assert client.post(f"/api/v1/corrections/{edit['id']}/undo").status_code == 200
    for identifier in (record["id"], other_id):
        data = client.get(f"/api/v1/recordings/{identifier}/transcript").json()
        assert data["revision"] == 3 and data["rows"][0]["speaker_id"] == a
