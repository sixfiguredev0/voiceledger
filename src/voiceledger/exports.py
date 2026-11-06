import csv
import io
import json


def timestamp(ms: int, srt=False) -> str:
    hours, remainder = divmod(max(0, ms), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if srt else '.'}{millis:03}"


def cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_recordings(recordings: list[dict], speakers: dict[str, str], format: str, include_excluded=False):
    groups = [
        {**r, "turns": [t for t in r["turns"] if include_excluded or not t["excluded"]]} for r in recordings
    ]
    if format == "json":
        return json.dumps(
            {"schema_version": 1, "recordings": groups, "speakers": speakers}, ensure_ascii=False, indent=2
        ).encode("utf-8"), "application/json"
    output = io.StringIO()
    if format == "csv":
        writer = csv.writer(output)
        writer.writerow(
            ["recording", "speaker", "start_ms", "end_ms", "text", "category", "uncertain", "excluded"]
        )
        for record in groups:
            for turn in record["turns"]:
                name = speakers.get(turn["speaker_id"], turn["cluster"] or "Unknown")
                writer.writerow(
                    [
                        cell(record["filename"]),
                        cell(name),
                        turn["start_ms"],
                        turn["end_ms"],
                        cell(turn["text"]),
                        turn["category"],
                        turn["uncertain"],
                        turn["excluded"],
                    ]
                )
        return output.getvalue().encode("utf-8-sig"), "text/csv"
    if format == "txt":
        for record in groups:
            output.write(f"\n=== {record['filename']} ===\n")
            for turn in record["turns"]:
                name = speakers.get(turn["speaker_id"], turn["cluster"] or "Unknown")
                output.write(f"[{timestamp(turn['start_ms'])}] {name}: {turn['text']}\n")
        return output.getvalue().encode("utf-8"), "text/plain"
    if format == "srt":
        index, offset = 1, 0
        for record in groups:
            for turn in record["turns"]:
                if not turn["text"].strip():
                    continue
                name = speakers.get(turn["speaker_id"], turn["cluster"] or "Unknown")
                label = f"[{record['filename']}] " if len(groups) > 1 else ""
                output.write(
                    f"{index}\n{timestamp(offset + turn['start_ms'], True)} --> "
                    f"{timestamp(offset + turn['end_ms'], True)}\n{label}{name}: {turn['text']}\n\n"
                )
                index += 1
            offset += record["duration_ms"]
        return output.getvalue().encode("utf-8"), "application/x-subrip"
    raise ValueError("Export format must be txt, srt, csv or json.")
