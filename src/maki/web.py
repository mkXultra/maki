"""Lightweight HTTP server for confirm UI (runs in a daemon thread)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from maki.confirm import ConfirmChoice, ConfirmStore

TEMPLATE_DIR = Path(__file__).parent / "templates"


def load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text()


class MakiHandler(BaseHTTPRequestHandler):
    store: ConfirmStore

    def log_message(self, format, *args):
        pass  # suppress logs

    def _check_token(self) -> bool:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        if token != self.store.token:
            self.send_error(403, "Invalid token")
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            if not self._check_token():
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(load_template("dashboard.html").encode())

        elif path == "/api/pending":
            if not self._check_token():
                return
            pending = self.store.list_pending()
            data = [
                {"id": r.id, "job_name": r.job_name, "agent_output": r.agent_output}
                for r in pending
            ]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/respond":
            if not self._check_token():
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            req_id = body.get("id", "")
            choice_str = body.get("choice", "")
            edit_text = body.get("edit_text")

            choice_map = {"accept": ConfirmChoice.ACCEPT, "reject": ConfirmChoice.REJECT, "edit": ConfirmChoice.EDIT}
            choice = choice_map.get(choice_str)
            if not choice:
                self.send_error(400, "Invalid choice")
                return

            ok = self.store.resolve(req_id, choice, edit_text)
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": ok}).encode())

        else:
            self.send_error(404)


def start_server(store: ConfirmStore, host: str = "127.0.0.1", port: int = 7831) -> str:
    """Start the HTTP server in a daemon thread. Returns the dashboard URL."""

    class Handler(MakiHandler):
        pass

    Handler.store = store  # type: ignore
    server = HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://{host}:{port}/?token={store.token}"
