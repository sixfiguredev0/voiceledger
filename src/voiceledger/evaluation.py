"""Explicit evaluation against user-reviewed reference data. Never self-grade model output."""

import unicodedata


def tokens(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(" " if unicodedata.category(c).startswith("P") else c for c in normalized)
    return normalized.split()


def word_errors(reference, hypothesis):
    if not reference:
        raise ValueError("The reviewed reference contains no words in the selected region.")
    previous = [(0, 0, index) for index in range(len(hypothesis) + 1)]
    for index, expected in enumerate(reference, 1):
        current = [(0, index, 0)]
        for column, actual in enumerate(hypothesis, 1):
            if expected == actual:
                current.append(previous[column - 1])
            else:
                s, d, i = previous[column - 1]
                substitution = (s + 1, d, i)
                s, d, i = previous[column]
                deletion = (s, d + 1, i)
                s, d, i = current[column - 1]
                insertion = (s, d, i + 1)
                current.append(min((substitution, deletion, insertion), key=sum))
        previous = current
    substitutions, deletions, insertions = previous[-1]
    return {
        "reference_words": len(reference),
        "hypothesis_words": len(hypothesis),
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "word_error_rate": sum(previous[-1]) / len(reference),
    }


def evaluate(raw_rows, reference_rows, reference_speakers, mapping, start_ms=0, end_ms=None):
    reviewed = [
        r
        for r in reference_rows
        if not r.get("excluded") and r["start_ms"] >= start_ms and (end_ms is None or r["end_ms"] <= end_ms)
    ]
    if not reviewed:
        raise ValueError("No complete reference turns fit the selected evaluation interval.")
    left, right = min(r["start_ms"] for r in reviewed), max(r["end_ms"] for r in reviewed)
    reference = tokens(" ".join(r["text"] for r in reviewed))
    hypothesis = []
    for row in raw_rows:
        if row.get("words"):
            hypothesis.extend(
                w["text"] for w in row["words"] if left <= (w["start_ms"] + w["end_ms"]) / 2 < right
            )
        elif row["start_ms"] >= left and row["end_ms"] <= right:
            hypothesis.append(row["text"])
    report = {
        **word_errors(reference, tokens(" ".join(hypothesis))),
        "start_ms": left,
        "end_ms": right,
        "reference_source": "user-provided reviewed export",
        "speaker_attribution_accuracy": None,
        "speaker_evaluated_ms": 0,
    }
    if mapping:
        boundaries = {left, right}
        for row in raw_rows + reviewed:
            boundaries.update(max(left, min(right, row[key])) for key in ("start_ms", "end_ms"))
        boundaries = sorted(boundaries)
        correct = total = 0
        for start, end in zip(boundaries, boundaries[1:]):
            midpoint = (start + end) / 2
            truth = {
                reference_speakers[r["speaker_id"]]
                for r in reviewed
                if r.get("speaker_id") in reference_speakers
                and not r.get("overlap")
                and r["start_ms"] <= midpoint < r["end_ms"]
            }
            if len(truth) != 1:
                continue
            predicted = {
                mapping.get(r.get("cluster")) for r in raw_rows if r["start_ms"] <= midpoint < r["end_ms"]
            }
            total += end - start
            if predicted == truth:
                correct += end - start
        report["speaker_evaluated_ms"] = total
        report["speaker_attribution_accuracy"] = correct / total if total else None
    return report
