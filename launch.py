"""Start the dashboard, local-only ingest API, and inbox collector together."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    env = os.environ.copy()
    env.setdefault("UEBA_DATA_DIR", str(ROOT / "data"))
    data_root = Path(env["UEBA_DATA_DIR"]).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    bind_address = env.get("UEBA_BIND_ADDRESS", "127.0.0.1")
    web_port = int(env.get("PORT", "8501"))
    commands = [
        [sys.executable, "-m", "ueba.service", "--root", str(data_root / "workspaces")],
        [sys.executable, "-m", "ueba.api", "--host", "127.0.0.1", "--port", "8600"],
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py"),
         "--server.address", bind_address, "--server.port", str(web_port), "--server.headless", "true"],
    ]
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
        print(f"UEBA console: http://{bind_address}:{web_port}")
        print("Ingest API: http://127.0.0.1:8600 (loopback only)")
        print("Collector checks each workspace inbox every 10 seconds. Press Ctrl+C to stop all three.")
        while True:
            failed = [child for child in children if child.poll() is not None]
            if failed:
                raise RuntimeError("A UEBA component stopped. Check its terminal output.")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
