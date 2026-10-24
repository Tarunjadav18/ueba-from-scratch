"""Small token-authenticated JSON API using only the Python standard library."""
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .auth import verify_token
from .storage import audit
from .workspace import WorkspaceManager

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10_000


class IngestHandler(BaseHTTPRequestHandler):
    server_version = "UEBAIngest/1.0"

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"ok": True, "service": "ueba-ingest-api"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self) -> None:
        match = re.fullmatch(r"/v1/workspaces/([a-zA-Z0-9_-]+)/events", self.path)
        if not match:
            self._respond(404, {"error": "not found"})
            return
        workspace = match.group(1).lower()
        authorization = self.headers.get("Authorization", "")
        if not authorization.lower().startswith("bearer "):
            self._respond(401, {"error": "Bearer token required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("Request body must be between 1 byte and 8 MiB.")
            body = json.loads(self.rfile.read(length))
            events = body.get("events") if isinstance(body, dict) else None
            if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
                raise ValueError(f"Send an events array containing 1 to {MAX_EVENTS} records.")
        except (ValueError, json.JSONDecodeError) as exc:
            self._respond(400, {"error": str(exc)})
            return
        try:
            root = Path(os.environ.get("UEBA_DATA_DIR", "data"))
            actor = verify_token(root / "console.db", authorization.split(None, 1)[1], workspace)
            manager = WorkspaceManager(root / "workspaces")
            target = manager.get(workspace) / "inbox" / (
                f"api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
            )
        except FileNotFoundError:
            self._respond(404, {"error": "workspace not found"})
            return
        except PermissionError as exc:
            self._respond(401, {"error": str(exc)})
            return
        target.write_text(json.dumps({"events": events}, separators=(",", ":")))
        audit(root / "console.db", "api_batch_queued", actor, workspace, f"events={len(events)}")
        self._respond(202, {"accepted": len(events), "queued_file": target.name, "workspace": workspace})

    def log_message(self, fmt: str, *args) -> None:
        # Avoid writing authorization headers or request bodies to the service log.
        print(f"API {self.address_string()} {fmt % args}")


def serve(host: str = "127.0.0.1", port: int = 8600) -> None:
    server = ThreadingHTTPServer((host, port), IngestHandler)
    print(f"UEBA ingest API listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local UEBA ingest API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
