"""The page on the dashboard's address while MemorySafe's first start sets itself up.

The install guide names http://127.0.0.1:8765/dashboard as the proof an install worked, but
the dashboard needs the runtime the first start is still building, so for that minute or
several the address refused connections -- and a tester downloaded the extension three
times in three minutes. The bootstrap proxy serves this page there instead until the
runtime is ready, and the real dashboard then answers at the same address.

Standard library only, and parses as Python 3.8: it runs inside the proxy, on whatever
python3 the machine already has.
"""

from __future__ import annotations

import html
import json
import os
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .provisioning import STEPS, describe


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
POLL_SECONDS = 2.0


def setup_port() -> int:
    """The dashboard's port, from the variable claude_launcher and setup_app read."""
    try:
        return int(os.environ.get("MEMORYSAFE_SETUP_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def dashboard_url(port: int) -> str:
    return "http://%s:%d/dashboard" % (HOST, port)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="2">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MemorySafe setup</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 36rem;
       margin: 3rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.4rem; }}
li.done {{ opacity: 0.6; }}
li.now {{ font-weight: 600; }}
code {{ word-break: break-all; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>
"""

_TITLES = {
    "failed": "MemorySafe could not finish setting up",
    "interrupted": "MemorySafe's setup stopped part-way",
    "ready": "MemorySafe is ready",
}


def _steps(status: Dict[str, Any]) -> str:
    current = status.get("step_number") or 0
    items = []
    for number, (_name, label) in enumerate(STEPS, 1):
        if number < current:
            items.append('<li class="done">&#10003; %s</li>' % html.escape(label))
        elif number == current:
            items.append('<li class="now">%s&hellip;</li>' % html.escape(label))
        else:
            items.append("<li>%s</li>" % html.escape(label))
    return "<ol>\n%s\n</ol>" % "\n".join(items)


def render_page(
    status: Dict[str, Any],
    explanation: Optional[Tuple[str, List[str]]] = None,
    install_log: Optional[str] = None,
) -> str:
    """The whole page for one status. explanation is degraded_server.explain's (headline, actions)."""

    state = status.get("status")
    parts: List[str] = []
    if state == "failed":
        headline, actions = explanation or (describe(status), [])
        parts.append("<p>%s</p>" % html.escape(headline))
        if actions:
            parts.append("<ul>\n%s\n</ul>" % "\n".join("<li>%s</li>" % html.escape(action) for action in actions))
        parts.append("<p>Ask your assistant to run the MemorySafe doctor.</p>")
        if install_log:
            parts.append("<p>Install log: <code>%s</code></p>" % html.escape(install_log))
    elif state == "interrupted":
        parts.append("<p>%s</p>" % html.escape(describe(status)))
    elif state == "ready":
        parts.append("<p>Setup is finished. Your dashboard is starting at this address.</p>")
    else:
        parts.append("<p>%s</p>" % html.escape(describe(status)))
        parts.append(_steps(status))
        parts.append(
            "<p>This page turns into your dashboard when setup finishes. "
            "You do not need to download anything again.</p>"
        )
    title = _TITLES.get(state, "MemorySafe is installed")
    return _TEMPLATE.format(title=html.escape(title), body="\n".join(parts))


class _PageServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """A plain threading TCP server rather than http.server.HTTPServer, for two reasons.

    HTTPServer.server_bind resolves the host's fully qualified name, a DNS lookup that can
    stall on a machine with a slow resolver; nothing here needs it.

    And HTTPServer turns on SO_REUSEADDR, which on Windows lets a second socket bind a port
    another one is already listening on. This page must fail to bind while anything else
    holds the dashboard's address -- that failure is how it knows to wait -- so on Windows
    it asks for the address exclusively. POSIX keeps SO_REUSEADDR, which there only allows
    rebinding past TIME_WAIT.
    """

    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        if os.name == "nt":
            self.allow_reuse_address = False
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        socketserver.TCPServer.server_bind(self)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A browser that closes mid-reply is not worth a traceback in the host's MCP log.
        pass


class ProgressPage:
    """Serves the progress page on the dashboard's address until the runtime is ready.

    status() is re-read every poll_seconds whether or not anyone is looking: the page must
    never outlive an unready runtime, because the real dashboard only starts on a free
    address. A failed bind -- another host's proxy already serving this page, or an older
    dashboard -- is retried on the same poll, so a host that quits mid-build hands the page
    on to the next one.
    """

    def __init__(
        self,
        port: int,
        status: Callable[[], Dict[str, Any]],
        render: Callable[[Dict[str, Any]], str],
        host: str = HOST,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._address = (host, port)
        self._status = status
        self._render = render
        self._poll_seconds = poll_seconds
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="memorysafe-progress-page", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop serving; returns once the address is free, or after timeout."""
        self._stopping.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _finished(self) -> bool:
        try:
            return self._status().get("status") == "ready"
        except Exception:
            return False

    def _run(self) -> None:
        server: Optional[_PageServer] = None
        try:
            while not self._stopping.is_set() and not self._finished():
                if server is None:
                    server = self._bind()
                self._stopping.wait(self._poll_seconds)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()

    def _bind(self) -> Optional[_PageServer]:
        try:
            server = _PageServer(self._address, self._handler())
        except OSError:
            return None
        threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.25},
            name="memorysafe-progress-http",
            daemon=True,
        ).start()
        return server

    def _handler(self) -> type:
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    status = page._status()
                    if urlsplit(self.path).path == "/api/status":
                        # No product and no version: to claude_launcher's stale-dashboard
                        # check and doctor's dashboard_version check this is not a
                        # dashboard, so neither tries to stop it or reports it as old.
                        body = json.dumps({"provisioning": status}).encode("utf-8")
                        self._send(503, "application/json", body)
                    else:
                        self._send(200, "text/html; charset=utf-8", page._render(status).encode("utf-8"))
                except Exception:
                    self._send(500, "text/plain; charset=utf-8", b"MemorySafe is setting itself up.")

            def _send(self, code: int, kind: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                # Request lines would pile up in the host's MCP log, which is stderr.
                pass

        return Handler
