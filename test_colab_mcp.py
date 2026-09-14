import asyncio
import json
import sys
import os

UVX_PATH = os.path.expanduser("~/.local/bin/uvx")
SERVER_CMD = [UVX_PATH, "git+https://github.com/googlecolab/colab-mcp"]

TEST_PYTHON_CODE = """import sys, platform
try:
    import torch
    cuda_avail = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU"
except Exception as e:
    cuda_avail = False
    device_name = f"Error: {e}"

print("=" * 50)
print(f" Python Version : {platform.python_version()}")
print(f" System Platform: {platform.platform()}")
print(f" GPU Available  : {cuda_avail} ({device_name})")
print(" 🚀 Successfully executed code in Google Colab via MCP!")
print("=" * 50)
"""

def extract_text_from_result(result_obj):
    """Extracts text content or raw result from an MCP tool response."""
    if not isinstance(result_obj, dict):
        return str(result_obj)
    if "structuredContent" in result_obj and "result" in result_obj["structuredContent"]:
        return str(result_obj["structuredContent"]["result"])
    contents = result_obj.get("content", [])
    text_parts = []
    for c in contents:
        if isinstance(c, dict) and c.get("type") == "text":
            text_parts.append(c.get("text", ""))
    if text_parts:
        return "\n".join(text_parts).strip()
    if "result" in result_obj:
        return str(result_obj["result"])
    return json.dumps(result_obj)

def extract_cell_id(result_obj):
    """Extracts the actual clean cell ID string from the add_code_cell response."""
    text = extract_text_from_result(result_obj)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data.get("newCellId") or data.get("cellId") or data.get("id") or text
    except Exception:
        pass
    import re
    match = re.search(r'["\']newCellId["\']\s*:\s*["\']([^"\']+)["\']', text)
    if match:
        return match.group(1)
    return text.strip('"\' \n{}')

async def read_stream(stream, prefix="[STDERR]"):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip()
        if text:
            # Filter out deprecation warnings for cleaner output
            if "DeprecationWarning" not in text:
                print(f"{prefix} {text}")

async def main():
    print("=" * 65)
    print("🚀 Colab MCP Test Client: Auto Connect, Add Cell & Execute")
    print(f"📡 Command: {' '.join(SERVER_CMD)}")
    print("=" * 65)

    proc = await asyncio.create_subprocess_exec(
        *SERVER_CMD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    asyncio.create_task(read_stream(proc.stderr, prefix="[LOG]"))

    request_id = 0

    async def send_msg(obj):
        data = json.dumps(obj) + "\n"
        proc.stdin.write(data.encode("utf-8"))
        await proc.stdin.drain()

    async def read_msg():
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

    async def call_tool(tool_name, arguments):
        nonlocal request_id
        request_id += 1
        curr_id = request_id
        await send_msg({
            "jsonrpc": "2.0",
            "id": curr_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        })
        while True:
            msg = await read_msg()
            if msg is None:
                raise RuntimeError("Server closed stdout while waiting for tool response")
            if msg.get("id") == curr_id:
                return msg.get("result", {})
            elif msg.get("method") == "notifications/tools/list_changed":
                print("\n🔔 Notification: tools/list_changed received")

    # 1. Initialize
    request_id += 1
    print("\n1️⃣  Performing MCP Handshake (initialize)...")
    await send_msg({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
            },
            "clientInfo": {
                "name": "colab-mcp-full-test",
                "version": "1.0.0"
            }
        }
    })
    init_res = await read_msg()
    print("   Handshake initialized successfully!")

    # 2. Initialized notification
    await send_msg({
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })

    # 3. Call open_colab_browser_connection
    print("\n2️⃣  Connecting to Colab Browser Session...")
    print("👉 Checking connection or opening Colab tab...")
    conn_result = await call_tool("open_colab_browser_connection", {})
    print(f"   Connection result: {conn_result}")

    # 4. Wait for tools/list_changed or verify tools
    print("\n3️⃣  Querying available notebook tools...")
    request_id += 1
    await send_msg({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/list",
        "params": {}
    })
    tools_res = await read_msg()
    tools = {t["name"]: t for t in tools_res.get("result", {}).get("tools", [])}
    
    # If tools not yet unlocked, wait briefly for notification
    if "add_code_cell" not in tools:
        print("   Waiting for Colab tab to pair and unlock tools...")
        while "add_code_cell" not in tools:
            msg = await read_msg()
            if msg and msg.get("method") == "notifications/tools/list_changed":
                request_id += 1
                await send_msg({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                    "params": {}
                })
                tools_res = await read_msg()
                tools = {t["name"]: t for t in tools_res.get("result", {}).get("tools", [])}

    print(f"   Available Tools: {', '.join(tools.keys())}")

    # 5. Add code cell
    print("\n4️⃣  Inserting test code cell into your Colab notebook...")
    print("─" * 50)
    print(TEST_PYTHON_CODE.strip())
    print("─" * 50)
    
    add_result = await call_tool("add_code_cell", {
        "cellIndex": 0,
        "language": "python",
        "code": TEST_PYTHON_CODE
    })
    print(f"   [DEBUG] Raw add_result: {json.dumps(add_result)}")
    
    cell_id = extract_cell_id(add_result)
    print(f"   ✅ Code cell inserted successfully! Cell ID: '{cell_id}'")

    # 6. Execute the code cell
    print(f"\n5️⃣  Executing cell '{cell_id}' in the cloud kernel...")
    print("⏳ Running on Google Colab runtime... please wait a moment...")
    
    exec_result = await call_tool("run_code_cell", {
        "cellId": cell_id
    })
    print(f"   [DEBUG] Raw exec_result: {json.dumps(exec_result)}")

    print("\n" + "=" * 65)
    print("🎉 EXECUTION OUTPUT RECEIVED FROM GOOGLE COLAB:")
    print("=" * 65)
    output_text = extract_text_from_result(exec_result)
    print(output_text)
    print("=" * 65)

    print("\n👀 Check your browser tab—you'll see the cell and output live in Colab!")
    print("Press Ctrl+C to disconnect and close the test client.\n")

    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\nCleaning up server process...")
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        print("Done.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
