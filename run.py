# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastapi>=0.110.0",
#     "uvicorn>=0.28.0",
#     "pydantic>=2.0.0",
# ]
# ///

#!/usr/bin/env python3
import sys
import os
import shutil

# If running directly with system python without dependencies, auto-rerun with uv
try:
    import uvicorn
    import fastapi
    import pydantic
except ImportError:
    uv_path = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if os.path.isfile(uv_path) and os.access(uv_path, os.X_OK):
        print("⚡ Automatically activating virtual environment via uv...")
        os.execv(uv_path, [uv_path, "run", os.path.abspath(__file__)] + sys.argv[1:])
    else:
        print("\n⚠️  Missing required dependencies ('fastapi', 'uvicorn', 'pydantic').")
        print("👉 Run with: uv run run.py")
        sys.exit(1)

import socket

def find_available_port(preferred_port=8000):
    for port in [preferred_port, 8080, 8081, 8888, 5000]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return preferred_port

def main():
    port = int(os.environ.get("PORT", 0)) or find_available_port(8000)
    print("=" * 65)
    print("🚀 Starting Colab Web MCP Application")
    print("   Persistent Cloud Execution Bridge for Humans & Agents")
    print("=" * 65)
    print(f"\n🌐 Dashboard: http://localhost:{port}")
    print("🔌 Starting Colab daemon in the background...\n")

    uvicorn.run("app.server:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
