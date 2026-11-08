import runpy
from pathlib import Path

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "check_publication.py"))
inspect_sensitive = CHECK["inspect_sensitive"]


def test_credentials_rejected_without_echoing_the_value():
    value = "hf_" + "x" * 30
    failures = inspect_sensitive("docs/example.md", value.encode())
    assert failures and all(value not in failure for failure in failures)
    assert inspect_sensitive("auth.json", b"{}")
    assert inspect_sensitive("private.zip", b"archive")


def test_only_the_known_public_audio_is_allowed():
    root = Path(__file__).resolve().parents[1]
    public = (root / "demo" / "audio" / "session-1.flac").read_bytes()
    assert not inspect_sensitive("demo/audio/session-1.flac", public)
    assert inspect_sensitive("demo/audio/session-1.flac", b"replaced with private recording")
    assert inspect_sensitive("demo/audio/unattributed.flac", public)


def test_normal_source_and_explicit_example_configuration_are_allowed():
    assert not inspect_sensitive("src/voiceledger/config.py", b"token = get_token()")
    assert not inspect_sensitive(".env.example", b"VOICELEDGER_THREADS=8")
