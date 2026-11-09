import random
from pathlib import Path

from voiceledger.launcher import Cat, main, screen


def test_cat_rests_then_moves_and_stays_inside_resized_windows():
    cat = Cat(rng=random.Random(12), next_move=10)
    cat.tick(5, 80)
    assert cat.mood == "rest" and cat.x == 4
    moods = set()
    for step in range(2000):
        width = 80 if step < 1000 else 24
        cat.tick(step / 5, width)
        assert 0 <= cat.x <= width - 17
        moods.add(cat.mood)
    assert {"rest", "walk", "blink"} <= moods


def test_screen_fits_small_consoles_and_does_not_offer_to_stop_an_attached_server():
    for width, height in [(88, 28), (40, 18), (15, 8), (1, 1)]:
        rows = screen(width, height, "Ready", Cat(), 3650, 8020)
        assert len(rows) == max(1, height - 1)
        assert all(len(row) <= max(1, width - 1) for row in rows)
    rows = screen(100, 28, "Connected", Cat(), 0, 8020, attached=True)
    assert "Close companion" in rows[-1] and "Stop safely" not in rows[-1]


def test_preview_uses_private_logs_without_starting_a_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VOICELEDGER_DATA_DIR", str(tmp_path))
    assert main(["--preview", "--seconds", "0.05", "--plain", "--no-browser"]) == 0
    assert "ready" in capsys.readouterr().out
    assert len(list((tmp_path / "logs").glob("studio-*.log"))) == 1
    assert not (tmp_path / "voiceledger.sqlite").exists()


def test_startup_failure_returns_a_log_path_and_no_traceback_on_screen(tmp_path, monkeypatch, capsys):
    from voiceledger import api

    monkeypatch.setenv("VOICELEDGER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("voiceledger.launcher.existing_studio", lambda port: False)

    def fail():
        raise RuntimeError("private diagnostic detail")

    monkeypatch.setattr(api, "create_app", fail)
    assert main(["--plain", "--no-browser"]) == 1
    output = capsys.readouterr().out
    assert "could not start" in output and "private diagnostic detail" not in output
    assert "private diagnostic detail" in next((tmp_path / "logs").glob("*.log")).read_text()


def test_attached_companion_never_creates_or_stops_a_server(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from voiceledger import api

    monkeypatch.setenv("VOICELEDGER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("voiceledger.launcher.existing_studio", lambda port: True)
    monkeypatch.setattr(api, "create_app", lambda: (_ for _ in ()).throw(AssertionError("duplicate server")))
    real_wait = threading.Event.wait

    def short_wait(self, timeout=None):
        if timeout is None:
            self.set()
            return True
        return real_wait(self, timeout)

    monkeypatch.setattr(threading.Event, "wait", short_wait)
    monkeypatch.setattr(
        "voiceledger.launcher.threading.Thread",
        lambda **kwargs: SimpleNamespace(start=lambda: None, join=lambda **kwargs: None),
    )
    assert main(["--plain", "--no-browser"]) == 0
    assert not (Path(tmp_path) / "voiceledger.sqlite").exists()
