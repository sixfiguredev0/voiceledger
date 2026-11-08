"""Reject private runtime artifacts and credentials before publishing tracked source."""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT = {
    ".gitignore",
    ".gitattributes",
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "README.bg.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "Setup.cmd",
    "Launch.cmd",
}
ALLOWED_DIRS = {"src", "frontend", "tests", "scripts", ".github", "demo", "docs"}
PRIVATE = {
    "node_modules",
    ".venv",
    ".tools",
    ".cache",
    "data",
    "private",
    "exports",
    "backups",
    "test-results",
    "playwright-report",
    "dist",
    "__pycache__",
}
SECRET = re.compile(r"(?:hf_[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})")
SECRET_EXTRA = re.compile(
    r"github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"
)
PUBLIC_AUDIO = {
    "demo/audio/session-1.flac": "3571e9fd4c80dcc2ade17a743d7d0fda53d51012cae008a8d7a5c6dc486910ee",
    "demo/audio/session-2.flac": "ca13c132c2169a17686d514e3b4e17a02f03dcd9aa4a90b49c6aa1d732a4132c",
}


def inspect_sensitive(relative, content):
    """Report filenames only. Never print a matched credential or private content."""
    path = Path(relative)
    failures = []
    if (
        path.name.lower()
        in {
            "auth.json",
            "credentials",
            "credentials.json",
            "token",
            "tokens.json",
            ".netrc",
            ".npmrc",
            ".pypirc",
            "id_rsa",
            "id_ed25519",
        }
        or path.name.lower().startswith(".env")
        and path.name != ".env.example"
        or path.suffix.lower()
        in {
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".zip",
            ".7z",
            ".tar",
            ".gz",
            ".srt",
            ".vtt",
            ".jsonl",
            ".sqlite3",
            ".log",
        }
    ):
        failures.append(f"Credential, export or archive file: {relative}")
    if path.suffix.lower() == ".flac":
        if hashlib.sha256(content).hexdigest() != PUBLIC_AUDIO.get(path.as_posix()):
            failures.append(f"Audio does not match the attributed public demo: {relative}")
    elif path.suffix.lower() not in {".png", ".jpg", ".woff2"}:
        value = content.decode("utf-8", errors="replace")
        if SECRET.search(value) or SECRET_EXTRA.search(value):
            failures.append(f"Possible credential: {relative}")
    return failures


def inspect_history():
    result = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], cwd=ROOT, capture_output=True, check=True
    )
    failures, count = [], 0
    for line in result.stdout.decode("utf-8").splitlines():
        fields = line.split(" ", 1)
        if len(fields) != 2:
            continue
        identifier, filename = fields
        kind = subprocess.run(
            ["git", "cat-file", "-t", identifier], cwd=ROOT, capture_output=True, check=True
        ).stdout.strip()
        if kind != b"blob":
            continue
        content = subprocess.run(
            ["git", "cat-file", "blob", identifier], cwd=ROOT, capture_output=True, check=True
        ).stdout
        count += 1
        relative = Path(filename)
        parts = relative.parts
        if (
            parts[0] not in ALLOWED_DIRS
            and filename not in ALLOWED_ROOT
            or any(part in PRIVATE for part in parts)
            or relative.suffix.lower()
            in {
                ".m4a",
                ".mp3",
                ".wav",
                ".aac",
                ".ogg",
                ".opus",
                ".mp4",
                ".webm",
                ".mov",
                ".mkv",
                ".npy",
                ".npz",
                ".pt",
                ".bin",
                ".sqlite",
                ".db",
                ".safetensors",
            }
        ):
            failures.append(f"Private/generated artifact in Git history: {filename}")
        failures.extend(inspect_sensitive(filename, content))
    return count, failures


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    failures = []
    files = [Path(name) for name in result.stdout.decode().split("\0") if name]
    for relative in files:
        path = ROOT / relative
        failures.extend(inspect_sensitive(relative.as_posix(), path.read_bytes()))
        parts = relative.parts
        if len(parts) == 1 and relative.name not in ALLOWED_ROOT:
            failures.append(f"Unexpected root file: {relative}")
        if len(parts) > 1 and parts[0] not in ALLOWED_DIRS:
            failures.append(f"Unexpected directory: {relative}")
        if any(part in PRIVATE for part in parts):
            failures.append(f"Private/generated directory: {relative}")
        suffix = path.suffix.lower()
        if suffix in {
            ".m4a",
            ".mp3",
            ".mp2",
            ".ogg",
            ".oga",
            ".opus",
            ".aac",
            ".aif",
            ".aiff",
            ".caf",
            ".wma",
            ".m4b",
            ".mp4",
            ".webm",
            ".mov",
            ".mkv",
            ".wav",
            ".flac",
            ".pt",
            ".bin",
            ".npy",
            ".npz",
            ".sqlite",
            ".db",
            ".safetensors",
        }:
            if not (
                parts[:2] == ("demo", "audio") and suffix == ".flac" and path.stat().st_size < 2 * 1024**2
            ):
                failures.append(f"Private audio, database or model artifact: {relative}")
        if path.stat().st_size > 5 * 1024**2:
            failures.append(f"Unexpected large file: {relative}")
        if suffix not in {".flac", ".png", ".jpg", ".woff2"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if SECRET.search(text):
                failures.append(f"Possible credential: {relative}")
            if re.search(r"[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+[\\/]", text):
                failures.append(f"Machine-specific user path: {relative}")
    history_count, history_failures = inspect_history()
    failures.extend(history_failures)
    if failures:
        print("\n".join(failures))
        sys.exit(1)
    print(f"Publication check passed for {len(files)} tracked source/demo files.")
    print(
        f"History check passed for {history_count} reachable file versions across local/remote branches and tags."
    )


if __name__ == "__main__":
    main()
