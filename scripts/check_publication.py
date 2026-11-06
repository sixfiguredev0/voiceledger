"""Reject private runtime artifacts and credentials before publishing tracked source."""

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


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    failures = []
    files = [Path(name) for name in result.stdout.decode().split("\0") if name]
    for relative in files:
        path = ROOT / relative
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
    if failures:
        print("\n".join(failures))
        sys.exit(1)
    print(f"Publication check passed for {len(files)} tracked source/demo files.")


if __name__ == "__main__":
    main()
