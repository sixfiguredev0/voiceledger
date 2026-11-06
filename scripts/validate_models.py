"""Opt-in smoke test against a running localhost app using attributed public audio.

Creates a separate 'Public model validation' project. Requires downloaded fast and
diarization models. It exercises real workers, cancellation, resume and references.
No credentials or private recordings are embedded in this script.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8020")
    parser.add_argument("--output", default=".cache/public-model-validation.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "demo" / "manifest.json").read_text(encoding="utf-8"))
    client = httpx.Client(base_url=args.url + "/api/v1", timeout=30)
    client.headers["x-voiceledger-token"] = client.get("/session").json()["token"]

    def post(path, value=None, **kwargs):
        result = client.post(path, json=value, **kwargs)
        result.raise_for_status()
        return result.json()

    def wait(identifier, cancel=False):
        deadline = time.monotonic() + 1200
        requested = False
        previous = None
        while time.monotonic() < deadline:
            jobs = client.get("/jobs").json()
            job = next(j for j in jobs if j["id"] == identifier)
            state = (job["status"], job["stage"])
            if state != previous:
                print(json.dumps({"job": identifier[:8], "status": state[0], "stage": state[1]}), flush=True)
                previous = state
            if cancel and not requested and job["stage"] == "diarization" and job["status"] == "running":
                post(f"/jobs/{identifier}/cancel")
                requested = True
            if job["status"] in ("completed", "failed", "cancelled", "interrupted"):
                return job
            time.sleep(1)
        raise TimeoutError("Local model validation exceeded 20 minutes.")

    project = next(
        (p for p in client.get("/projects").json() if p["name"] == "Public model validation"), None
    )
    if project is None:
        project = post("/projects", {"name": "Public model validation"})
    records = []
    reports = []
    for index, item in enumerate(manifest["recordings"]):
        source = root / "demo" / "audio" / item["filename"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        existing = client.get(f"/projects/{project['id']}/recordings").json()
        record = next((r for r in existing if r["sha256"] == digest), None)
        if record is None:
            with source.open("rb") as handle:
                record = post(
                    f"/projects/{project['id']}/recordings",
                    files={"file": (item["filename"], handle, "audio/flac")},
                )
        records.append(record)
        job = post("/jobs", {"recording_id": record["id"], "mode": "fast", "language": "en"})
        result = wait(job["id"], cancel=index == 0)
        cancelled_and_resumed = result["status"] == "cancelled"
        if cancelled_and_resumed:
            # An ASR cache hit does not start another worker or produce a new peak-memory measurement.
            post(f"/jobs/{job['id']}/resume")
            result = wait(job["id"])
        assert result["status"] == "completed", result
        transcript = client.get(f"/recordings/{record['id']}/transcript?limit=2000").json()
        clusters = {r["cluster"] for r in transcript["rows"] if r["cluster"]}
        automatic_count = len(clusters)
        if automatic_count < 3:
            proposal = post(
                "/corrections/preview",
                {
                    "recording_id": record["id"],
                    "base_revision": transcript["revision"],
                    "actions": [
                        {
                            "kind": "reanalyze",
                            "row_ids": [r["id"] for r in transcript["rows"]],
                            "start_ms": 0,
                            "end_ms": record["metadata_json"]["duration_ms"],
                            "min_speakers": 3,
                        }
                    ],
                },
            )
            post(f"/proposals/{proposal['id']}/apply")
            recheck = next(
                j
                for j in client.get("/jobs").json()
                if j["recording_id"] == record["id"] and j["kind"] == "reanalyze"
            )
            result = wait(recheck["id"])
            assert result["status"] == "completed", result
            transcript = client.get(f"/recordings/{record['id']}/transcript?limit=2000").json()
            clusters = {r["cluster"] for r in transcript["rows"] if r["cluster"]}
        assert len(clusters) >= 3, f"Speaker-count correction did not produce three voices: {len(clusters)}"
        reports.append(
            {
                "automatic_speakers": automatic_count,
                "speakers_after_review_hint": len(clusters),
                "turns": len(transcript["rows"]),
                "details": result["details"],
                "cancel_resume_verified": cancelled_and_resumed,
            }
        )
        if index == 0:
            # The first source utterance is explicitly labeled Reader A by dataset metadata.
            reference = item["turns"][0]
            first = max(
                transcript["rows"],
                key=lambda row: max(
                    0, min(row["end_ms"], reference["end_ms"]) - max(row["start_ms"], reference["start_ms"])
                ),
            )
            proposal = post(
                "/corrections/preview",
                {
                    "recording_id": record["id"],
                    "base_revision": transcript["revision"],
                    "actions": [
                        {
                            "kind": "assign",
                            "row_ids": [first["id"]],
                            "name": "Public Reader A",
                            "scope": "cluster",
                        }
                    ],
                },
            )
            post(f"/proposals/{proposal['id']}/apply")
            speaker = client.get(f"/projects/{project['id']}/speakers").json()[0]
            sample = post(
                f"/speakers/{speaker['id']}/samples",
                {
                    "recording_id": record["id"],
                    "start_ms": reference["start_ms"],
                    "end_ms": reference["end_ms"],
                    "confirmed": True,
                },
            )
            jobs = client.get("/jobs").json()
            reference_job = next(
                j
                for j in jobs
                if j["kind"] == "reference" and j["settings"]["sample_id"] == sample["sample_id"]
            )
            reference_result = wait(reference_job["id"])
            assert reference_result["status"] == "completed", reference_result
    matches = client.get(f"/recordings/{records[1]['id']}/matches").json()
    assert any(m["candidates"] for m in matches), "No valid cross-recording reference comparisons"
    report = {
        "schema_version": 1,
        "dataset": manifest["source"],
        "project_id": project["id"],
        "recordings": reports,
        "reference_embedding_verified": True,
        "cross_recording_candidates_verified": True,
        "private_bulgarian_quality_evaluated": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
