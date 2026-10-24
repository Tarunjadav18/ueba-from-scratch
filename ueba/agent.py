"""Store-and-forward local endpoint telemetry agent."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _snapshot() -> list[dict]:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("Install the project requirements to use the endpoint agent.") from exc
    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    try:
        connections = len(psutil.net_connections(kind="inet"))
    except (psutil.AccessDenied, PermissionError):
        connections = 0
    now = datetime.now(timezone.utc).isoformat()
    user = getpass.getuser()
    device = socket.gethostname()
    common = {"timestamp": now, "user": user, "device": device, "department": "Unknown"}
    return [
        {**common, "event_type": "resource", "result": "sample", "resource_pct": cpu,
         "memory_pct": memory, "disk_pct": disk, "duration_seconds": 15},
        {**common, "event_type": "network", "result": "sample", "count": connections,
         "port": 0, "bytes_out": 0, "bytes_in": 0},
    ]


def _flush(url: str, workspace: str, token: str, queue_path: Path) -> bool:
    if not queue_path.exists():
        return True
    lines = queue_path.read_text().splitlines()
    if not lines:
        return True
    events = [json.loads(line) for line in lines]
    payload = json.dumps({"events": events}).encode()
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/workspaces/{workspace}/events", data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read()
        queue_path.write_text("")
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Send local resource and connection-count samples to UEBA.")
    parser.add_argument("--url", default="http://127.0.0.1:8600")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--token", default=os.environ.get("UEBA_API_TOKEN", ""))
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--queue", default="data/agent-queue.jsonl")
    args = parser.parse_args()
    if not args.token:
        parser.error("Pass --token or set UEBA_API_TOKEN.")
    queue_path = Path(args.queue)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        with queue_path.open("a") as queue:
            for event in _snapshot():
                queue.write(json.dumps(event, separators=(",", ":")) + "\n")
        ok = _flush(args.url, args.workspace, args.token, queue_path)
        print("sent" if ok else f"offline; queued data retained in {queue_path}")
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
