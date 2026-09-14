import asyncio
import json
import sys
import os

UVX_PATH = os.path.expanduser("~/.local/bin/uvx")
SERVER_CMD = [UVX_PATH, "git+https://github.com/googlecolab/colab-mcp"]

async def read_stream(stream, prefix="[SERVER]"):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip()
        if text:
            print(f"{prefix} {text}")

async def main():
    print("=" * 60)
    print("🚀 Starting Colab MCP Test Client")
    print(f"📡 Launching server: {' '.join(SERVER_CMD)}")
    print("=" * 60)

    proc = await asyncio.create_subprocess_exec(
        *SERVER_CMD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Background task to print stderr logs from server
    asyncio.create_task(read_stream(proc.stderr, prefix="[STDERR]"))

    request_id = 0

    async def send_json(obj):
        data = json.dumps(obj) + "\n"
        proc.stdin.write(data.encode("utf-8"))
        await proc.stdin.drain()

    async def read_json():
        while True:
            line = await proc.stdout.readline()
            if not line:
                return None
            line_str = line.decode(errors="replace").strip()
            if not line_str:
                continue
            try:
                return json.loads(line_str)
            except json.JSONDecodeError:
                print(f"[STDOUT RAW] {line_str}")

    # 1. Initialize Handshake
    request_id += 1
    init_msg = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
            },
            "clientInfo": {
                "name": "colab-mcp-tester",
                "version": "1.0.0"
            }
        }
    }
    print(f"\n📤 Sending 'initialize'...")
    await send_json(init_msg)
    init_response = await read_json()
    print("📥 Received initialize response:")
    print(json.dumps(init_response, indent=2))

    # 2. Initialized Notification
    await send_json({
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })
    print("📤 Sent 'notifications/initialized'")

    # 3. List initial tools
    request_id += 1
    await send_json({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/list",
        "params": {}
    })
    tools_response = await read_json()
    tools = tools_response.get("result", {}).get("tools", [])
    print(f"\n🔧 Initial Available Tools ({len(tools)}):")
    for t in tools:
        print(f"  - {t.get('name')}: {t.get('description')}")

    # 4. Call open_colab_browser_connection
    print("\n" + "=" * 60)
    print("🌐 Calling 'open_colab_browser_connection'...")
    print("👉 Watch your browser! A Google Colab tab should open.")
    print("=" * 60)

    request_id += 1
    await send_json({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "open_colab_browser_connection",
            "arguments": {}
        }
    })

    # 5. Listen for tool result & dynamic updates
    print("\n⏳ Listening for server events, WebSocket handshake, and tool notifications...")
    print("(Press Ctrl+C at any time to exit)\n")

    try:
        while True:
            msg = await read_json()
            if msg is None:
                print("\n[INFO] Server closed stdout stream.")
                break

            # If it's a response to open_colab_browser_connection
            if msg.get("id") == request_id:
                print("\n🎉 'open_colab_browser_connection' Call Result:")
                print(json.dumps(msg, indent=2))

            # If tools/list_changed notification is received
            elif msg.get("method") == "notifications/tools/list_changed":
                print("\n🔔 NOTIFICATION: tools/list_changed received! Refreshing tool list...")
                request_id += 1
                await send_json({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                    "params": {}
                })
            elif "result" in msg and "tools" in msg["result"]:
                refreshed_tools = msg["result"]["tools"]
                print(f"\n✨ Unlocked Tools ({len(refreshed_tools)}):")
                for t in refreshed_tools:
                    print(f"  ⭐ {t.get('name')}: {t.get('description')}")
                print("\n✅ Colab is now successfully paired and ready for code execution!")
            else:
                print(f"📨 Server message: {json.dumps(msg)}")
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\nStopping...")
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        print("Done.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
