#!/usr/bin/env python3
"""
IMNID Hub Standalone Application Launcher
Health Information Interoperability & Data Platform

Provides a unified runner for desktop, system service, and console deployments:
- Launches the FastAPI backend server (uvicorn)
- Automatically mounts and serves the React single-page frontend (dist/)
- Intelligently manages user data, logs, and database in persistent storage
- Launches the default web browser upon startup (can be disabled via --no-browser)
"""

import os
import sys
import time
import argparse
import webbrowser
import threading
from pathlib import Path

# Ensure application root directory is on Python search path
APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

def open_browser(url: str, delay: float = 1.2):
    """Open default web browser after server initializes."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Thread(target=_open, daemon=True)
    t.start()

def main():
    parser = argparse.ArgumentParser(
        description="IMNID Hub - Health Information Interoperability Platform"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host IP to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8085, help="Port to bind (default: 8085)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--data-dir", default=None, help="Custom path for data/db/exports storage")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["DATA_DIR"] = str(Path(args.data_dir).resolve())

    # Import backend app and settings after configuring environment
    from backend.core.config import settings
    from backend.app import app
    import uvicorn

    bind_host = args.host
    bind_port = args.port or settings.BACKEND_PORT
    display_host = "localhost" if bind_host in ("0.0.0.0", "127.0.0.1") else bind_host
    hub_url = f"http://{display_host}:{bind_port}"

    print("=" * 68)
    print("  IMNID Hub - Health Information Interoperability Platform")
    print(f"  Access UI at: {hub_url}")
    print(f"  Data Directory: {settings.DATA_DIR}")
    print("=" * 68)

    if not args.no_browser and not os.getenv("IMNID_NO_BROWSER"):
        open_browser(hub_url)

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")

if __name__ == "__main__":
    main()

