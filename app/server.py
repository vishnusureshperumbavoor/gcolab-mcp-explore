from contextlib import asynccontextmanager
import os
import sys
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from app.mcp_client import client

class ExecuteRequest(BaseModel):
    code: str
    keep_cell: bool = True

class RunCellRequest(BaseModel):
    cell_id: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the persistent Colab MCP client daemon
    print("[SERVER] Starting persistent Colab MCP daemon...")
    await client.start()
    yield
    # Shutdown: Stop the client process
    print("[SERVER] Stopping Colab MCP daemon...")
    await client.stop()

app = FastAPI(title="Google Colab Web MCP Bridge", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/status")
async def get_status():
    """Returns the current connection status and active tools."""
    return {
        "status": client.status,
        "message": client.status_message,
        "tools": list(client.tools.keys()),
        "connected": client.status == "connected",
        "recent_logs": list(client.logs)[-25:]
    }

@app.post("/api/connect")
async def connect_colab():
    """Initiates pairing with Google Colab tab via open_colab_browser_connection."""
    res = await client.connect_browser()
    return res

@app.post("/api/execute")
async def execute_code(req: ExecuteRequest):
    """Executes Python code in Google Colab and returns execution output."""
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty.")
    
    try:
        result = await client.execute_code(req.code, keep_cell=req.keep_cell)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cells")
async def get_cells():
    """Returns the notebook cells from the connected Colab tab."""
    try:
        cells = await client.get_notebook_cells()
        return {"cells": cells}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cells/run")
async def run_cell(req: RunCellRequest):
    """Executes an existing cell by its cell ID."""
    if not req.cell_id:
        raise HTTPException(status_code=400, detail="cell_id is required")
    try:
        res = await client.run_existing_cell(req.cell_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/cells/{cell_id}")
async def delete_cell(cell_id: str):
    """Deletes a cell from the Colab notebook."""
    try:
        res = await client.delete_existing_cell(cell_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
