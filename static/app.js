// Snippet Templates
const SNIPPETS = {
  gpu_check: `import sys, platform
try:
    import torch
    cuda_avail = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU"
except Exception as e:
    cuda_avail = False
    device_name = f"Error: {e}"

print("=" * 45)
print(f" Python Version : {platform.python_version()}")
print(f" OS / Platform  : {platform.platform()}")
print(f" GPU Available  : {cuda_avail} ({device_name})")
print("=" * 45)
!nvidia-smi
`,
  benchmark: `import torch, time

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🚀 Running Matrix Multiplication on: {device.upper()}")

size = 4096
x = torch.randn(size, size, device=device)
y = torch.randn(size, size, device=device)

# Warmup
_ = torch.matmul(x, y)
if device == "cuda":
    torch.cuda.synchronize()

start = time.time()
for _ in range(10):
    _ = torch.matmul(x, y)
if device == "cuda":
    torch.cuda.synchronize()
elapsed = (time.time() - start) / 10

print(f"✅ {size}x{size} matmul average: {elapsed * 1000:.2f} ms")
`,
  disk_info: `import os, psutil, shutil

total, used, free = shutil.disk_usage("/")
print("=" * 45)
print(f" Cloud Disk Total: {total // (2**30)} GB")
print(f" Cloud Disk Used : {used // (2**30)} GB")
print(f" Cloud Disk Free : {free // (2**30)} GB")
print(f" CPU Count       : {os.cpu_count()}")
print(f" Total RAM       : {psutil.virtual_memory().total // (2**30)} GB")
print("=" * 45)
`,
  pip_install: `!pip install einops rich
import einops, rich
rich.print("[bold green]✅ Packages installed and imported successfully![/bold green]")
`
};

// DOM Elements
const statusBadge = document.getElementById("statusBadge");
const statusText = document.getElementById("statusText");

const codeEditor = document.getElementById("codeEditor");
const snippetSelector = document.getElementById("snippetSelector");
const keepCellToggle = document.getElementById("keepCellToggle");
const btnClearCode = document.getElementById("btnClearCode");
const btnExecute = document.getElementById("btnExecute");
const runIcon = document.getElementById("runIcon");
const runSpinner = document.getElementById("runSpinner");
const runBtnLabel = document.getElementById("runBtnLabel");

const outputPre = document.getElementById("outputPre");
const terminalPlaceholder = document.querySelector(".terminal-placeholder");
const execTimer = document.getElementById("execTimer");
const btnCopyOutput = document.getElementById("btnCopyOutput");
const btnClearOutput = document.getElementById("btnClearOutput");

const tabBtns = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");
const btnRefreshCells = document.getElementById("btnRefreshCells");
const cellsList = document.getElementById("cellsList");

let isRunning = false;
let executionStartTime = 0;
let timerInterval = null;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupEditor();
  setupEvents();
  checkStatus();
  setInterval(checkStatus, 3000); // Periodic status check
  
  // Load default snippet
  codeEditor.value = SNIPPETS.gpu_check;
});

// Tab Switching
function setupTabs() {
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      tabBtns.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));
      
      btn.classList.add("active");
      const content = document.getElementById(targetTab);
      if (content) content.classList.add("active");

      if (targetTab === "notebookTab") {
        fetchCells();
      }
    });
  });
}

// Editor setup: Tab indent & shortcut
function setupEditor() {
  codeEditor.addEventListener("keydown", (e) => {
    // Tab key inserts 4 spaces
    if (e.key === "Tab") {
      e.preventDefault();
      const start = codeEditor.selectionStart;
      const end = codeEditor.selectionEnd;
      codeEditor.value = codeEditor.value.substring(0, start) + "    " + codeEditor.value.substring(end);
      codeEditor.selectionStart = codeEditor.selectionEnd = start + 4;
    }
    // Ctrl + Enter or Cmd + Enter to execute
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      executeCurrentCode();
    }
  });
}

let isConnected = false;

// Event Listeners
function setupEvents() {
  snippetSelector.addEventListener("change", (e) => {
    const key = e.target.value;
    if (SNIPPETS[key]) {
      codeEditor.value = SNIPPETS[key];
    }
  });

  btnClearCode.addEventListener("click", () => {
    codeEditor.value = "";
    codeEditor.focus();
  });

  btnExecute.addEventListener("click", () => {
    executeCurrentCode();
  });

  btnClearOutput.addEventListener("click", () => {
    outputPre.textContent = "";
    outputPre.classList.add("hidden");
    terminalPlaceholder.classList.remove("hidden");
    execTimer.classList.add("hidden");
  });

  btnCopyOutput.addEventListener("click", () => {
    const text = outputPre.textContent;
    if (text) {
      navigator.clipboard.writeText(text);
      btnCopyOutput.style.color = "#34d399";
      setTimeout(() => { btnCopyOutput.style.color = ""; }, 1500);
    }
  });

  btnRefreshCells.addEventListener("click", fetchCells);
}

// Status Poller
async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    
    updateStatusUI(data);
  } catch (err) {
    console.error("Status check failed:", err);
  }
}

function updateStatusUI(data) {
  isConnected = !!data.connected;
  statusBadge.className = "status-pill";
  if (data.connected) {
    statusBadge.classList.add("status-connected");
    statusText.textContent = "Colab: Connected";
  } else if (data.status === "connecting") {
    statusBadge.classList.add("status-connecting");
    statusText.textContent = "Colab: Connecting Tab...";
  } else {
    statusBadge.classList.add("status-ready");
    statusText.textContent = "Colab: Ready (Auto-connects on run)";
  }
}

// Code Execution
async function executeCurrentCode() {
  const code = codeEditor.value.trim();
  if (!code || isRunning) return;

  isRunning = true;
  setExecutingState(true);

  // Switch to terminal tab
  document.querySelector('[data-tab="terminalTab"]').click();

  terminalPlaceholder.classList.add("hidden");
  outputPre.classList.remove("hidden");
  
  if (!isConnected) {
    outputPre.textContent = "⚡ Colab tab not connected.\n👉 Automatically opening Google Colab in your browser and connecting...\n⏳ Please wait a moment while the session pairs...\n";
  } else {
    outputPre.textContent = "⏳ Executing in Google Colab cloud kernel...\n";
  }

  executionStartTime = Date.now();
  execTimer.classList.remove("hidden");
  execTimer.textContent = "0.0s";
  timerInterval = setInterval(() => {
    const secs = ((Date.now() - executionStartTime) / 1000).toFixed(1);
    execTimer.textContent = `${secs}s`;
  }, 100);

  try {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: code,
        keep_cell: keepCellToggle.checked
      })
    });

    const data = await res.json();
    clearInterval(timerInterval);
    const totalDuration = ((Date.now() - executionStartTime) / 1000).toFixed(2);
    execTimer.textContent = `Completed in ${totalDuration}s`;

    if (!res.ok) {
      outputPre.textContent = `❌ Error: ${data.detail || "Execution failed"}`;
    } else {
      let out = data.output || "No output returned.";
      outputPre.textContent = out;
      isConnected = true;
      checkStatus();
    }
  } catch (err) {
    clearInterval(timerInterval);
    outputPre.textContent = `❌ Network Error: ${err.message}`;
  } finally {
    isRunning = false;
    setExecutingState(false);
  }
}

function setExecutingState(executing) {
  if (executing) {
    runIcon.classList.add("hidden");
    runSpinner.classList.remove("hidden");
    runBtnLabel.textContent = "Running...";
    btnExecute.disabled = true;
  } else {
    runIcon.classList.remove("hidden");
    runSpinner.classList.add("hidden");
    runBtnLabel.textContent = "Run on Colab";
    btnExecute.disabled = false;
  }
}

// Cells list
async function fetchCells() {
  cellsList.innerHTML = '<div class="empty-state">Loading notebook cells...</div>';
  try {
    const res = await fetch("/api/cells");
    const data = await res.json();
    const cells = data.cells || [];

    if (cells.length === 0) {
      cellsList.innerHTML = '<div class="empty-state">No cells found in active notebook.</div>';
      return;
    }

    cellsList.innerHTML = "";
    cells.forEach((c, idx) => {
      const item = document.createElement("div");
      item.className = "cell-item";
      
      const type = c.cell_type || c.type || "code";
      const snippet = (c.source || c.content || c.code || "").slice(0, 60).replace(/\n/g, " ");
      const id = c.id || c.cell_id || `cell-${idx}`;

      item.innerHTML = `
        <div class="cell-meta">
          <span class="cell-badge">${type}</span>
          <span class="cell-snippet">#${idx + 1}: ${escapeHtml(snippet)}</span>
        </div>
        <div class="cell-actions">
          ${type === "code" ? `<button class="btn btn-secondary btn-sm" onclick="runSpecificCell('${id}')">Run</button>` : ''}
          <button class="btn btn-ghost btn-sm" onclick="deleteSpecificCell('${id}')">Delete</button>
        </div>
      `;
      cellsList.appendChild(item);
    });
  } catch (err) {
    cellsList.innerHTML = `<div class="empty-state">Failed to load cells: ${err.message}</div>`;
  }
}

window.runSpecificCell = async function(cellId) {
  try {
    document.querySelector('[data-tab="terminalTab"]').click();
    terminalPlaceholder.classList.add("hidden");
    outputPre.classList.remove("hidden");
    outputPre.textContent = `⏳ Running cell '${cellId}'...\n`;
    
    const res = await fetch("/api/cells/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cell_id: cellId })
    });
    const data = await res.json();
    outputPre.textContent = data.output || "Completed with no output.";
  } catch (err) {
    outputPre.textContent = `❌ Error: ${err.message}`;
  }
};

window.deleteSpecificCell = async function(cellId) {
  if (!confirm(`Delete cell ${cellId}?`)) return;
  try {
    await fetch(`/api/cells/${cellId}`, { method: "DELETE" });
    fetchCells();
  } catch (err) {
    alert(`Failed to delete cell: ${err.message}`);
  }
};

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}
