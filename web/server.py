"""
Unified startup script for the Quant Engine web UI.

Usage:
    python -m web.server              # Start both backend (8000) and frontend (3000)
    python -m web.server --backend    # Start only the backend
    python -m web.server --frontend   # Start only the frontend
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def start_backend() -> subprocess.Popen:
    """Start the FastAPI backend server."""
    print("[server] Starting backend on http://127.0.0.1:8000 ...")
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "web.backend.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--reload",
        ],
        cwd=str(ROOT),
    )


def start_frontend() -> subprocess.Popen:
    """Start the Next.js frontend dev server."""
    # Ensure node_modules exist
    if not (FRONTEND_DIR / "node_modules").exists():
        print("[server] Installing frontend dependencies...")
        subprocess.run(
            ["npm", "install"],
            cwd=str(FRONTEND_DIR),
            check=True,
        )

    print("[server] Starting frontend on http://127.0.0.1:3000 ...")
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(FRONTEND_DIR),
    )


def main():
    parser = argparse.ArgumentParser(description="Quant Engine Web Server")
    parser.add_argument("--backend", action="store_true", help="Start only backend")
    parser.add_argument("--frontend", action="store_true", help="Start only frontend")
    args = parser.parse_args()

    # If neither flag is set, start both
    start_be = not args.frontend or args.backend
    start_fe = not args.backend or args.frontend
    if not args.backend and not args.frontend:
        start_be = start_fe = True

    processes: list[subprocess.Popen] = []

    def shutdown(sig=None, frame=None):
        print("\n[server] Shutting down...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if start_be:
        processes.append(start_backend())

    if start_fe:
        processes.append(start_frontend())

    if start_be and start_fe:
        print("\n" + "=" * 50)
        print("  Quant Engine Web UI")
        print("  Frontend: http://127.0.0.1:3000")
        print("  Backend:  http://127.0.0.1:8000")
        print("  Press Ctrl+C to stop")
        print("=" * 50 + "\n")

    # Wait for any process to exit
    try:
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f"[server] Process {p.pid} exited with code {p.returncode}")
                    shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
