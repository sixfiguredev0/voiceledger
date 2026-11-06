from __future__ import annotations

import copy

from sqlalchemy import select, update

from .database import Correction, Proposal, Recording, Run, Speaker, serialize, uid
from .schemas import Action


class Conflict(ValueError):
    pass


def speaker_redirects(session, project_id):
    recording_ids = select(Recording.id).where(Recording.project_id == project_id)
    redirects = {}
    for edit in session.scalars(
        select(Correction)
        .where(Correction.recording_id.in_(recording_ids), Correction.active.is_(True))
        .order_by(Correction.created_at)
    ):
        for action in edit.actions:
            if action["kind"] == "merge":
                redirects[action["source_speaker_id"]] = action["speaker_id"]
    return redirects


def canonical_speaker(identifier, redirects):
    visited = set()
    while identifier in redirects:
        if identifier in visited:
            raise ValueError("Speaker merges contain a cycle. Undo the conflicting merge first.")
        visited.add(identifier)
        identifier = redirects[identifier]
    return identifier


def apply_rows(rows: list, action: dict, *, replay=False) -> list:
    if not replay:
        rows = copy.deepcopy(rows)
    kind = action["kind"]
    if kind == "reanalyze":
        return rows
    if kind == "merge":
        for row in rows:
            if row["speaker_id"] == action["source_speaker_id"]:
                row["speaker_id"] = action["speaker_id"]
        return rows
    identifiers = set(action.get("row_ids", []))
    targets = [r for r in rows if r["id"] in identifiers]
    missing = identifiers - {r["id"] for r in targets}
    if missing:
        raise Conflict("Some edited turns changed during reanalysis. Review this saved correction.")
    if not targets:
        raise ValueError("Select at least one transcript turn.")
    if kind == "split":
        for row in targets:
            if not row["start_ms"] < action["split_at_ms"] < row["end_ms"]:
                raise ValueError("The split must be inside the selected turn.")
            if (
                not row.get("words")
                and row["text"]
                and (action.get("text") is None or action.get("right_text") is None)
            ):
                raise ValueError("For manually edited text, provide text for both sides of the split.")
    for row in targets:
        row["manual"] = True
        if kind == "assign":
            row["speaker_id"] = action["speaker_id"]
        elif kind == "text":
            row["text"] = action["text"]
            row["words"] = []
            row["category"] = "speech"
        elif kind == "bounds":
            row["start_ms"], row["end_ms"] = action["start_ms"], action["end_ms"]
            row["words"] = [
                w
                for w in row.get("words", [])
                if w["start_ms"] >= row["start_ms"] and w["end_ms"] <= row["end_ms"]
            ]
        elif kind == "mark":
            category = action["category"]
            row.update(
                category=category,
                excluded=category in ("noise", "irrelevant"),
                overlap=category == "overlap",
                uncertain=category in ("uncertain", "overlap"),
            )
        elif kind == "split":
            point = action["split_at_ms"]
            if not row["start_ms"] < point < row["end_ms"]:
                raise ValueError("The split must be inside the selected turn.")
            right = copy.deepcopy(row)
            right["id"] = f"{row['id']}:split:{point}"
            right["start_ms"] = point
            row["end_ms"] = point
            left_words = [w for w in row.get("words", []) if (w["start_ms"] + w["end_ms"]) / 2 < point]
            right_words = [w for w in row.get("words", []) if (w["start_ms"] + w["end_ms"]) / 2 >= point]
            row["text"] = (
                action["text"]
                if action.get("text") is not None
                else "".join(w["text"] for w in left_words).strip()
            )
            right["text"] = (
                action.get("right_text")
                if action.get("right_text") is not None
                else "".join(w["text"] for w in right_words).strip()
            )
            row["words"], right["words"] = left_words, right_words
            rows.append(right)
    return sorted(rows, key=lambda r: r["start_ms"])


def effective_rows(session, recording: Recording) -> tuple[list, list]:
    run = session.get(Run, recording.current_run_id) if recording.current_run_id else None
    rows = copy.deepcopy(run.raw_rows) if run else []
    conflicts = []
    project_recordings = select(Recording.id).where(Recording.project_id == recording.project_id)
    edits = session.scalars(
        select(Correction)
        .where(Correction.recording_id.in_(project_recordings), Correction.active.is_(True))
        .order_by(Correction.created_at)
    ).all()
    for edit in edits:
        for action in edit.actions:
            if edit.recording_id != recording.id and action["kind"] != "merge":
                continue
            try:
                rows = apply_rows(rows, action, replay=True)
            except (Conflict, ValueError) as exc:
                conflicts.append({"correction_id": edit.id, "explanation": str(exc), "actions": edit.actions})
    redirects = speaker_redirects(session, recording.project_id)
    for row in rows:
        row["speaker_id"] = canonical_speaker(row["speaker_id"], redirects)
    return rows, conflicts


def preview(
    session, recording: Recording, base_revision: int, actions: list[Action], explanation="Manual correction"
):
    if recording.revision != base_revision:
        raise Conflict("The transcript changed. Refresh it before applying this correction.")
    rows, _ = effective_rows(session, recording)
    duration = recording.metadata_json["duration_ms"]
    normalized = []
    affected = set()
    redirects = speaker_redirects(session, recording.project_id)
    pending_names = {}
    for typed in actions:
        action = typed.model_dump()
        if action["kind"] in ("bounds", "split") and len(action["row_ids"]) != 1:
            raise ValueError("Select exactly one turn to split or adjust.")
        for field in ("start_ms", "end_ms", "split_at_ms"):
            if action.get(field) is not None and action[field] > duration:
                raise ValueError("The selected time is outside this recording.")
        for field in ("speaker_id", "source_speaker_id"):
            if action.get(field):
                speaker = session.get(Speaker, action[field])
                if not speaker or speaker.project_id != recording.project_id:
                    raise ValueError("The speaker is not registered in this project.")
        if action["kind"] == "merge" and action["speaker_id"] == action["source_speaker_id"]:
            raise ValueError("Choose two different speakers.")
        if action["kind"] == "merge":
            proposed = {**redirects, action["source_speaker_id"]: action["speaker_id"]}
            canonical_speaker(action["source_speaker_id"], proposed)
            redirects = proposed
            for other in session.scalars(
                select(Recording).where(Recording.project_id == recording.project_id)
            ):
                other_rows, _ = effective_rows(session, other)
                affected.update(
                    (other.id, r["id"]) for r in other_rows if r["speaker_id"] == action["source_speaker_id"]
                )
        if action["kind"] == "assign" and action["speaker_id"]:
            action["speaker_id"] = canonical_speaker(action["speaker_id"], redirects)
        if action["kind"] == "reanalyze":
            run = session.get(Run, recording.current_run_id) if recording.current_run_id else None
            if run is None:
                raise ValueError("Process this recording before rechecking a region.")
            crossing = [
                r
                for r in run.raw_rows
                if r["end_ms"] > action["start_ms"] and r["start_ms"] < action["end_ms"]
            ]
            if crossing:
                action["start_ms"] = min(action["start_ms"], min(r["start_ms"] for r in crossing))
                action["end_ms"] = max(action["end_ms"], max(r["end_ms"] for r in crossing))
            action["row_ids"] = [
                r["id"] for r in rows if r["end_ms"] > action["start_ms"] and r["start_ms"] < action["end_ms"]
            ]
        if action["scope"] == "cluster":
            selected = [r for r in rows if r["id"] in action["row_ids"]]
            if len({r["cluster"] for r in selected}) != 1 or any(r["cluster"] is None for r in selected):
                raise ValueError("Select one detected speaker before applying to all its turns.")
            cluster = selected[0]["cluster"]
            action["row_ids"] = [r["id"] for r in rows if r["cluster"] == cluster]
        if action["kind"] == "assign" and action.get("name") and not action["speaker_id"]:
            existing = session.scalar(
                select(Speaker).where(
                    Speaker.project_id == recording.project_id, Speaker.name == action["name"].strip()
                )
            )
            if existing and canonical_speaker(existing.id, redirects) != existing.id:
                raise ValueError("This profile has been merged. Choose its current registered identity.")
            key = action["name"].strip()
            action["speaker_id"] = existing.id if existing else pending_names.setdefault(key, uid())
        rows = apply_rows(rows, action)
        if action["kind"] != "merge":
            affected.update((recording.id, identifier) for identifier in action["row_ids"])
        normalized.append(action)
    proposal = Proposal(
        recording_id=recording.id, base_revision=base_revision, actions=normalized, explanation=explanation
    )
    session.add(proposal)
    session.commit()
    return {**serialize(proposal), "affected_turns": len(affected)}


def apply_proposal(session, proposal: Proposal):
    recording = session.get(Recording, proposal.recording_id)
    if proposal.applied or proposal.clarification:
        raise Conflict("This proposal is already applied or requires clarification.")
    if recording.revision != proposal.base_revision:
        raise Conflict("The transcript changed. Request a fresh preview.")
    # Compare-and-swap prevents two browser tabs from committing the same revision.
    changed = session.execute(
        update(Recording)
        .where(Recording.id == recording.id, Recording.revision == proposal.base_revision)
        .values(revision=proposal.base_revision + 1)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise Conflict("The transcript changed in another window.")
    if any(action["kind"] == "merge" for action in proposal.actions):
        session.execute(
            update(Recording)
            .where(Recording.project_id == recording.project_id, Recording.id != recording.id)
            .values(revision=Recording.revision + 1)
        )
    for action in proposal.actions:
        if (
            action["kind"] == "assign"
            and action.get("name")
            and not session.get(Speaker, action["speaker_id"])
        ):
            session.add(
                Speaker(id=action["speaker_id"], project_id=recording.project_id, name=action["name"].strip())
            )
    correction = Correction(
        recording_id=recording.id,
        revision=proposal.base_revision + 1,
        actions=proposal.actions,
        explanation=proposal.explanation,
    )
    session.add(correction)
    session.flush()
    rechecks = [action for action in proposal.actions if action["kind"] == "reanalyze"]
    if rechecks:
        if len(rechecks) != 1:
            raise ValueError("Recheck one region at a time.")
        active = session.scalar(
            select(Run).where(
                Run.recording_id == recording.id, Run.status.in_(["queued", "running", "cancelling"])
            )
        )
        if active:
            raise Conflict("Wait for this recording's current job before rechecking speakers.")
        current = session.get(Run, recording.current_run_id)
        action = rechecks[0]
        session.add(
            Run(
                recording_id=recording.id,
                mode=current.mode,
                language=current.language,
                kind="reanalyze",
                settings={
                    "region": [action["start_ms"], action["end_ms"]],
                    "min_speakers": action["min_speakers"],
                    "max_speakers": action["max_speakers"],
                    "previous_run_id": current.id,
                    "correction_id": correction.id,
                },
            )
        )
    proposal.applied = True
    session.commit()
    return correction


def undo_correction(session, edit: Correction):
    if not edit or not edit.active:
        raise ValueError("This correction is missing or already undone.")
    record = session.get(Recording, edit.recording_id)
    for run in session.scalars(select(Run).where(Run.recording_id == record.id, Run.kind == "reanalyze")):
        if run.settings.get("correction_id") != edit.id:
            continue
        if run.status == "completed" and record.current_run_id != run.id:
            raise Conflict("A newer analysis depends on this recheck. Undo the newer recheck first.")
        if record.current_run_id == run.id:
            record.current_run_id = run.settings["previous_run_id"]
        if run.status in ("running", "queued"):
            run.status = "cancelling" if run.status == "running" else "cancelled"
    edit.active = False
    revision = session.scalar(
        update(Recording)
        .where(Recording.id == record.id)
        .values(revision=Recording.revision + 1)
        .returning(Recording.revision)
    )
    if any(action["kind"] == "merge" for action in edit.actions):
        session.execute(
            update(Recording)
            .where(Recording.project_id == record.project_id, Recording.id != record.id)
            .values(revision=Recording.revision + 1)
        )
    return revision
