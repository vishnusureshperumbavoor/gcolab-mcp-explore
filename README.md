# Google Colab Web MCP Bridge (`gcolab_mcp_web_mcp`)

A persistent web application and agent execution bridge for **Google Colab Model Context Protocol (MCP)**.

---

## Why this exists

Normally, executing code through standard MCP scripts starts a new server process every run, causing Google Colab to open a brand-new browser tab on every single command.

**`gcolab_mcp_web_mcp` solves this:**
- It runs a **single persistent background daemon** that pairs with your Google Colab tab **once**.
- You can execute unlimited commands, scripts, machine learning workloads, or shell commands with **zero new tabs opened**.
- Exposes both a **sleek dark-mode Web Dashboard** and a **REST/JSON API for AI agents**.

---

## Quick Start

### 1. Launch the Application

You can now start it with **any** of these simple commands (no flags needed):

```bash
./start.sh
```
or
```bash
python3 run.py
```
or
```bash
uv run run.py
```
*(Dependencies are declared inside `run.py` and are automatically handled on the fly).*

### 2. Open the Dashboard
Navigate to [http://localhost:8000](http://localhost:8000) in your browser.

### 3. Connect Colab Once
- Click **"Connect Colab Tab"** (or open the provided URL in your browser).
- Your Colab tab will display: *"Connected to local Colab MCP server"*.
- The dashboard status indicator turns 🟢 **Connected to Colab**.

---

## Features

1. **One-Click Cloud Code Execution**:
   - Write Python or shell commands (e.g., `!nvidia-smi`, `!pip install`) and run them directly on Colab's cloud GPU.
   - Shortcut: `Ctrl + Enter` to execute.
2. **Real-time Terminal Output**:
   - Live stdout, stderr, execution timer, copy output, and plot support.
3. **Notebook Cell Manager**:
   - Inspect all existing cells in your Google Colab notebook, run specific cells, or delete cells directly from the dashboard.
4. **AI Agent Integration API**:
   - External agents (or scripts) can send code to Colab via a simple HTTP request:

```bash
curl -X POST http://localhost:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "import torch; print(torch.cuda.is_available())"}'
```

```python
import requests

response = requests.post("http://localhost:8000/api/execute", json={
    "code": "!nvidia-smi"
})
print(response.json()["output"])
```
