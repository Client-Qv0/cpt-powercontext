#!/usr/bin/env python3
"""Run the RelayDesk backend server."""

import os
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

import uvicorn

if __name__ == "__main__":
    # Set data directory
    data_dir = os.environ.get("RELAYDESK_DATA_DIR", str(Path(__file__).parent / "data"))
    os.environ["RELAYDESK_DATA_DIR"] = data_dir

    print(f"Starting RelayDesk server...")
    print(f"Data directory: {data_dir}")
    print(f"Server: http://127.0.0.1:8000")
    print(f"API docs: http://127.0.0.1:8000/docs")

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
