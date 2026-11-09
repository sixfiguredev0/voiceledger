"""A quiet terminal companion. The server keeps its ordinary main-thread shutdown."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

GOLD = "\x1b[38;2;237;201;140m"
SAGE = "\x1b[38;2;162;196;177m"
MUTED = "\x1b[38;2;130;153;142m"
WHITE = "\x1b[38;2;231;237;227m"
BASE = "\x1b[48;2;14;22;22m"


@dataclass
class Cat:
    rng: random.Random = field(default_factory=random.Random)
    x: int = 4
    target: int = 4
    mood: str = "rest"
    next_move: float = 0
    frame: int = 0

    def tick(self, now: float, width: int):
        limit = max(0, width - 17)
        self.x, self.target = min(self.x, limit), min(self.target, limit)
        if now < self.next_move:
            return
        if self.mood == "walk" and self.x != self.target:
            self.x += 1 if self.target > self.x else -1
            self.frame += 1
            self.next_move = now + 0.14
        elif self.mood in ("blink", "look"):
            self.mood, self.next_move = "rest", now + self.rng.uniform(7, 16)
        elif self.mood == "walk":
            self.mood, self.next_move = "rest", now + self.rng.uniform(8, 20)
        else:
            self.mood = self.rng.choice(["walk", "walk", "blink", "look"])
            self.target = self.rng.randint(0, limit)
            self.next_move = now + (0.14 if self.mood == "walk" else 0.8)

    def art(self):
        if self.mood == "walk":
            left = self.target < self.x
            head = " < /\\_/\\" if left else "  /\\_/\\ >"
            return [head, " ( o.o )____~", "  /|   |\\" if self.frame % 2 else "  \\|___|/"]
        eyes = "-.-" if self.mood == "blink" else "o.O" if self.mood == "look" else "o.o"
        return ["   /\\_/\\", f"  ( {eyes} )", "  / >_< \\__~"]


def screen(width: int, height: int, status: str, cat: Cat, elapsed: int, port: int, attached=False):
    """Plain lines keep layout testable and never expose recording names or account data."""
    width, height = max(1, width - 1), max(1, height - 1)
    lines = [""] * height

    def put(row, value):
        if 0 <= row < height:
            lines[row] = value[:width]

    put(1, "    | |  |  | |     V O I C E L E D G E R")
    put(2, "    | | ||| | |     Your local listening studio")
    put(4, "    " + "-" * max(0, min(65, width - 8)))
    put(6, "    " + status)
    put(8, f"    Open your workspace   http://127.0.0.1:{port}")
    put(10, "    Recordings stay on your computer. This window keeps the studio open.")
    put(
        12,
        f"    {'CONNECTED' if attached else 'STUDIO'}  /  {elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}",
    )
    if height >= 23:
        put(height - 7, "    A small companion. Occasionally busy doing absolutely nothing.")
        for index, row in enumerate(cat.art()):
            put(height - 5 + index, " " * cat.x + row)
        put(height - 2, "    " + "_" * max(0, min(65, width - 8)))
    put(
        height - 1,
        "    [O] Open app    [L] Open log    [Q] " + ("Close companion" if attached else "Stop safely"),
    )
    if height < 17:
        put(0, " VoiceLedger | " + status)
        put(1, f" http://127.0.0.1:{port}  [O] Open  [L] Log  [Q] Quit")
    return lines


class Terminal:
    def __init__(self, output, plain=False):
        self.output, self.animated, self.previous = output, output.isatty() and not plain, []
        self.handle = self.old_mode = None
        if self.animated and os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.windll.kernel32
            kernel.GetStdHandle.restype = wintypes.HANDLE
            kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.handle = kernel.GetStdHandle(-11)
            mode = wintypes.DWORD()
            if kernel.GetConsoleMode(self.handle, ctypes.byref(mode)):
                self.old_mode = mode.value
                self.animated = bool(kernel.SetConsoleMode(self.handle, mode.value | 4))
            else:
                self.animated = False

    def __enter__(self):
        if self.animated:
            self.output.write("\x1b[?1049h\x1b[?25l" + BASE + "\x1b[2J")
            self.output.flush()
        return self

    def draw(self, lines):
        if not self.animated:
            return
        result = []
        if len(lines) != len(self.previous):
            result.append("\x1b[2J")
        for index, line in enumerate(lines):
            if index >= len(self.previous) or line != self.previous[index]:
                color = GOLD if index in (1, 6) else SAGE if index >= len(lines) - 5 else MUTED
                if index == 8:
                    color = WHITE
                result.append(f"\x1b[{index + 1};1H{BASE}{color}{line}\x1b[K")
        self.output.write("".join(result))
        self.output.flush()
        self.previous = lines

    def __exit__(self, *args):
        if self.animated:
            self.output.write("\x1b[0m\x1b[?25h\x1b[?1049l")
            self.output.flush()
        if self.old_mode is not None:
            import ctypes

            ctypes.windll.kernel32.SetConsoleMode(self.handle, self.old_mode)


def existing_studio(port):
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/openapi.json")
        # Local checks should never be routed through an environment proxy.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request, timeout=1
        ) as response:
            return json.load(response).get("info", {}).get("title") == "VoiceLedger"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_link(target, log):
    try:
        if isinstance(target, Path) and os.name == "nt":
            os.startfile(target)
        else:
            webbrowser.open(str(target))
    except Exception:
        # A missing file/browser association must not take away shutdown controls.
        traceback.print_exc(file=log)
        log.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description="VoiceLedger terminal companion")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--plain", action="store_true", help="Use a static status display")
    parser.add_argument(
        "--preview", action="store_true", help="Preview the companion without starting the app"
    )
    parser.add_argument("--seconds", type=float, default=12, help="Preview duration only")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or not 0 < args.seconds <= 3600:
        parser.error("Choose a port from 1024 to 65535 and a preview duration from 0 to 3600 seconds.")
    from .config import initialize_dirs

    root = initialize_dirs()
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"studio-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    console, done, server = sys.stdout, threading.Event(), None
    state = {"status": "Warming up your workspace...", "ready": args.preview}
    attached = False if args.preview else existing_studio(args.port)
    state["ready"] = args.preview or attached
    error = 0

    with Terminal(console, args.plain) as terminal, log_path.open("w", encoding="utf-8") as log:

        def companion():
            cat, started, opened, last_plain = Cat(), time.monotonic(), False, ""
            cat.next_move = started + 3
            while not done.is_set():
                now = time.monotonic()
                ready = state["ready"] or bool(server and server.started)
                status = (
                    ("Connected to your already-running studio." if attached else "Your studio is ready.")
                    if ready
                    else state["status"]
                )
                if server and server.should_exit:
                    status = "Closing safely. Saving progress..."
                if ready and not opened:
                    opened = True
                    if not args.no_browser and not args.preview:
                        open_link(f"http://127.0.0.1:{args.port}", log)
                size = shutil.get_terminal_size((88, 28))
                cat.tick(now, size.columns)
                terminal.draw(
                    screen(size.columns, size.lines, status, cat, int(now - started), args.port, attached)
                )
                if not terminal.animated and status != last_plain:
                    console.write(f"VoiceLedger | {status}\nhttp://127.0.0.1:{args.port}\nLog: {log_path}\n")
                    console.flush()
                    last_plain = status
                if os.name == "nt" and sys.stdin.isatty():
                    import msvcrt

                    if msvcrt.kbhit():
                        key = msvcrt.getwch().lower()
                        if key == "q":
                            if server:
                                server.should_exit = True
                            else:
                                done.set()
                        elif key == "o" and ready:
                            open_link(f"http://127.0.0.1:{args.port}", log)
                        elif key == "l":
                            log.flush()
                            open_link(log_path, log)
                done.wait(0.1 if cat.mood == "walk" or not ready else 0.3)

        thread = threading.Thread(target=companion, daemon=True, name="studio-companion")
        thread.start()
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                if args.preview:
                    done.wait(args.seconds)
                elif attached:
                    done.wait()
                else:
                    import uvicorn

                    from .api import create_app

                    state["status"] = "Opening your recordings and saved work..."
                    config = uvicorn.Config(create_app(), host="127.0.0.1", port=args.port, log_config=None)
                    import logging

                    handler = logging.StreamHandler(log)
                    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                    logger = logging.getLogger("uvicorn")
                    previous_handlers, previous_level, previous_propagate = (
                        logger.handlers[:],
                        logger.level,
                        logger.propagate,
                    )
                    logger.handlers, logger.level, logger.propagate = [handler], logging.INFO, False
                    try:
                        server = uvicorn.Server(config)
                        server.run()
                        if not server.started:
                            error = 1
                    finally:
                        logger.handlers, logger.level, logger.propagate = (
                            previous_handlers,
                            previous_level,
                            previous_propagate,
                        )
                        handler.close()
        except KeyboardInterrupt:
            pass
        except (Exception, SystemExit):
            traceback.print_exc(file=log)
            error = 1
        finally:
            done.set()
            thread.join(timeout=3)
    console.write(
        (
            "VoiceLedger could not start. See the private diagnostic log:\n"
            if error
            else "VoiceLedger companion closed.\n"
        )
        + str(log_path)
        + "\n"
    )
    console.flush()
    return error


if __name__ == "__main__":
    raise SystemExit(main())
