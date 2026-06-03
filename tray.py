import os
import subprocess
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
UVICORN = os.path.join(PROJECT_DIR, ".venv", "Scripts", "uvicorn.exe")
APP_URL = "http://127.0.0.1:8000"

_proc = None
_lock = threading.Lock()


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _make_icon(running: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = (76, 175, 80) if running else (198, 40, 40)
    draw.ellipse([8, 8, 56, 56], fill=fill)
    return img


def _start():
    global _proc
    with _lock:
        if _is_running():
            return
        _proc = subprocess.Popen(
            [UVICORN, "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def _stop():
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            _proc.wait()


def _refresh(icon):
    running = _is_running()
    icon.icon = _make_icon(running)
    icon.title = f"YT Summary — {'running :8000' if running else 'stopped'}"


def on_open(icon, item):
    webbrowser.open(APP_URL)


def on_toggle(icon, item):
    if _is_running():
        _stop()
    else:
        _start()
    _refresh(icon)


def on_quit(icon, item):
    _stop()
    icon.stop()


if __name__ == "__main__":
    _start()
    icon = pystray.Icon(
        "yt-summary",
        _make_icon(True),
        "YT Summary — running :8000",
        menu=pystray.Menu(
            pystray.MenuItem("Open in Browser", on_open, default=True),
            pystray.MenuItem(
                lambda item: "Stop Server" if _is_running() else "Start Server",
                on_toggle,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    icon.run()
