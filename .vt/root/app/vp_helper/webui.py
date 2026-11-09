"""Serve the merged xcpc-vp front end and its submission feed.

The site is a static build under ``web/dist``; one small endpoint returns the
mirror a running ``vp`` writes. A source checkout without a build falls back to
the Vite dev server so editing the front end stays live.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import sys
from urllib.request import urlopen

from .models import VPError

_FEED = "/api/vp-xcpc"


def web_root() -> Path:
    return Path(__file__).resolve().parent.parent / "web"


def build_directory() -> Path:
    return web_root() / "dist"


def has_build() -> bool:
    return (build_directory() / "index.html").is_file()


def has_source() -> bool:
    return (web_root() / "package.json").is_file()


def state_file() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "vp" / "xcpc-vp.json"


def feed(port: int) -> dict:
    """The payload the page would read, or an empty mapping when unreachable."""
    with urlopen(f"http://127.0.0.1:{port}{_FEED}", timeout=5) as response:
        return json.loads(response.read().decode("utf8") or "{}")


def reachable(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=1):
            return True
    except Exception:
        return False


class _Handler(SimpleHTTPRequestHandler):
    """Static files plus the one dynamic endpoint, served from the build."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] == _FEED:
            self._feed()
            return
        super().do_GET()

    def _feed(self) -> None:
        try:
            body = state_file().read_bytes()
        except OSError:
            body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def _serve_build(port: int) -> None:
    """Run the static server as its own process so it outlives ``vp``.

    A background thread would die with the launching process, which leaves the
    page unreachable once tmux takes over.
    """
    log = state_file().with_name("xcpc-vp.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as sink:
        subprocess.Popen([sys.executable, "-m", "vp_helper.webui", str(port)],
                         stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)


def serve(port: int) -> None:
    """Entry point of the standalone server process."""
    handler = partial(_Handler, directory=str(build_directory()))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def _serve_source(port: int) -> None:
    """Run the project's own dev server while editing the front end."""
    if shutil.which("pnpm") is None:
        raise VPError("pnpm is required to run the xcpc-vp source; build it with pnpm build:vp first.")
    log = state_file().with_name("xcpc-vp.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as sink:
        subprocess.Popen(["pnpm", "exec", "vite", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=web_root(), stdout=sink, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(240):
        if reachable(port):
            return
        time.sleep(0.25)
    raise VPError(f"xcpc-vp did not start; see {log}")


def ensure_served(port: int) -> None:
    """Make the site available on the port, preferring the built assets."""
    if reachable(port):
        return
    if has_build():
        _serve_build(port)
        for _ in range(80):
            if reachable(port):
                return
            time.sleep(0.25)
        raise VPError("the merged xcpc-vp did not start; see " + str(state_file().with_name("xcpc-vp.log")))
    if has_source():
        _serve_source(port)
        return
    raise VPError(f"no xcpc-vp front end found under {web_root()}")


if __name__ == "__main__":
    serve(int(sys.argv[1]))
