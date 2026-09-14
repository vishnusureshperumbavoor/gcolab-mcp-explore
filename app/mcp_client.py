import asyncio
import json
import os
import re
import sys
from collections import deque
from typing import Any, Dict, List, Optional

UVX_PATH = os.path.expanduser("~/.local/bin/uvx")
SERVER_CMD = [UVX_PATH, "git+https://github.com/googlecolab/colab-mcp"]

def extract_text_from_result(result_obj: Any) -> str:
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

def extract_cell_id(result_obj: Any) -> str:
    """Extracts clean cell ID from add_code_cell / add_text_cell response."""
    if isinstance(result_obj, dict):
        # Direct structuredContent
        if "structuredContent" in result_obj and isinstance(result_obj["structuredContent"], dict):
            sc = result_obj["structuredContent"]
            if "newCellId" in sc:
                return str(sc["newCellId"]).strip('"\' ')
        # Direct result dict
        if "result" in result_obj and isinstance(result_obj["result"], dict):
            r = result_obj["result"]
            if "newCellId" in r:
                return str(r["newCellId"]).strip('"\' ')
                
    text = extract_text_from_result(result_obj)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("newCellId") or data.get("cellId") or data.get("id") or text).strip('"\' ')
    except Exception:
        pass
        
    match = re.search(r'["\']newCellId["\']\s*:\s*["\']([^"\']+)["\']', text)
    if match:
        return match.group(1).strip()
        
    return text.strip('"\' \n{}')


class ColabMCPClient:
    def __init__(self):
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.status = "disconnected"  # disconnected, connecting, connected, error
        self.status_message = "Not started"
        self.tools: Dict[str, Any] = {}
        self.logs: deque = deque(maxlen=200)
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._connected_event = asyncio.Event()
        self._reader_tasks: List[asyncio.Task] = []

    def log(self, message: str):
        print(f"[ColabMCP] {message}")
        self.logs.append(message)

    async def start(self):
        """Starts the persistent colab-mcp subprocess and performs MCP handshake."""
        async with self._lock:
            if self.proc and self.proc.returncode is None:
                return

            self.status = "connecting"
            self.status_message = "Starting colab-mcp server process..."
            self.log(f"Launching server: {' '.join(SERVER_CMD)}")

            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *SERVER_CMD,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                self.status = "error"
                self.status_message = f"Failed to start server process: {e}"
                self.log(self.status_message)
                return

            self._reader_tasks = [
                asyncio.create_task(self._read_stdout()),
                asyncio.create_task(self._read_stderr()),
            ]

            # 1. MCP initialize handshake
            try:
                self._request_id += 1
                init_msg = {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "roots": {"listChanged": True},
                        },
                        "clientInfo": {
                            "name": "gcolab-web-mcp",
                            "version": "1.0.0"
                        }
                    }
                }
                self.log("Sending MCP initialize...")
                res = await self._send_request(init_msg)
                self.log(f"Initialized. Server: {res.get('serverInfo', {}).get('name', 'ColabMCP')}")

                # 2. notifications/initialized
                await self._send_notification("notifications/initialized", {})

                # 3. List initial tools
                await self.refresh_tools()

                self.status_message = "Server started. Ready to pair with Colab."
                self.log("colab-mcp server initialized successfully.")

            except Exception as e:
                self.status = "error"
                self.status_message = f"Handshake failed: {e}"
                self.log(self.status_message)

    async def _send_notification(self, method: str, params: Optional[Dict] = None):
        if not self.proc or not self.proc.stdin:
            return
        msg = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        data = json.dumps(msg) + "\n"
        self.proc.stdin.write(data.encode("utf-8"))
        await self.proc.stdin.drain()

    async def _send_request(self, msg: Dict[str, Any]) -> Any:
        req_id = msg["id"]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_futures[req_id] = future

        data = json.dumps(msg) + "\n"
        self.proc.stdin.write(data.encode("utf-8"))
        await self.proc.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=60.0)
        finally:
            self._pending_futures.pop(req_id, None)

    async def _read_stdout(self):
        while self.proc and self.proc.stdout:
            line = await self.proc.stdout.readline()
            if not line:
                break
            line_str = line.decode(errors="replace").strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
            except json.JSONDecodeError:
                self.log(f"[STDOUT RAW] {line_str}")
                continue

            # Handle responses to requests
            if "id" in msg and msg["id"] in self._pending_futures:
                fut = self._pending_futures[msg["id"]]
                if not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"].get("message", "MCP error")))
                    else:
                        fut.set_result(msg.get("result", {}))

            # Handle notifications from server
            elif "method" in msg:
                method = msg["method"]
                if method == "notifications/tools/list_changed":
                    self.log("Received notification: tools/list_changed. Refreshing tools...")
                    asyncio.create_task(self.refresh_tools())

    async def _read_stderr(self):
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if text and "DeprecationWarning" not in text:
                self.log(f"[SERVER] {text}")

    async def refresh_tools(self):
        """Fetches the updated list of tools from the MCP server."""
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
            "params": {}
        }
        res = await self._send_request(msg)
        tools_list = res.get("tools", [])
        self.tools = {t["name"]: t for t in tools_list}
        self.log(f"Active tools ({len(self.tools)}): {', '.join(self.tools.keys())}")

        if "add_code_cell" in self.tools and "run_code_cell" in self.tools:
            self.status = "connected"
            self.status_message = "Connected to Google Colab session! Ready for execution."
            self._connected_event.set()

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Executes a tool on the Colab MCP server."""
        if not self.proc or self.proc.returncode is not None:
            await self.start()

        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            }
        }
        return await self._send_request(msg)

    async def connect_browser(self) -> Dict[str, Any]:
        """Calls open_colab_browser_connection to pair with browser tab."""
        if self.status == "connected":
            return {"status": "already_connected", "message": "Already connected to Colab."}

        self.log("Calling open_colab_browser_connection...")
        self.status = "connecting"
        self.status_message = "Waiting for browser tab connection..."
        res = await self.call_tool("open_colab_browser_connection", {})
        return {"status": "connecting", "result": res}

    async def execute_code(self, code: str, keep_cell: bool = True) -> Dict[str, Any]:
        """Inserts a code cell into Colab, executes it, and returns the output."""
        if self.status != "connected":
            # Attempt auto-connection check
            await self.refresh_tools()
            if self.status != "connected":
                raise RuntimeError("Colab session is not connected. Please connect your Colab tab first.")

        async with self._lock:
            self.log("Inserting code cell...")
            add_res = await self.call_tool("add_code_cell", {
                "cellIndex": 0,
                "language": "python",
                "code": code
            })
            cell_id = extract_cell_id(add_res)
            self.log(f"Cell inserted with ID: '{cell_id}'. Running cell on kernel...")

            exec_res = await self.call_tool("run_code_cell", {
                "cellId": cell_id
            })

            output_text = extract_text_from_result(exec_res)
            is_error = exec_res.get("isError", False) if isinstance(exec_res, dict) else False

            if not keep_cell:
                try:
                    await self.call_tool("delete_cell", {"cellId": cell_id})
                except Exception:
                    pass

            return {
                "cellId": cell_id,
                "output": output_text,
                "isError": is_error,
                "raw": exec_res
            }

    async def get_notebook_cells(self) -> List[Dict[str, Any]]:
        """Retrieves all cells in the current Colab notebook."""
        if "get_cells" not in self.tools:
            return []
        res = await self.call_tool("get_cells", {"includeOutputs": True})
        text = extract_text_from_result(res)
        try:
            cells = json.loads(text)
            if isinstance(cells, list):
                return cells
            if isinstance(cells, dict) and "cells" in cells:
                return cells["cells"]
        except Exception:
            pass
        return []

    async def run_existing_cell(self, cell_id: str) -> Dict[str, Any]:
        """Runs an existing cell by its cell ID."""
        res = await self.call_tool("run_code_cell", {"cellId": cell_id})
        return {
            "cellId": cell_id,
            "output": extract_text_from_result(res),
            "isError": res.get("isError", False) if isinstance(res, dict) else False
        }

    async def delete_existing_cell(self, cell_id: str) -> Dict[str, Any]:
        """Deletes a cell by its cell ID."""
        res = await self.call_tool("delete_cell", {"cellId": cell_id})
        return {"cellId": cell_id, "result": res}

    async def stop(self):
        """Terminates the server process."""
        self.status = "disconnected"
        self.status_message = "Server stopped."
        for t in self._reader_tasks:
            t.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.log("Server process terminated.")

# Global singleton client instance
client = ColabMCPClient()
