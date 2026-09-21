# NotebookLM Clone - Windows installer.
# Run:  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 [-Dense]
# -Dense also installs torch CPU + sentence-transformers (semantic search + rerank).
param([switch]$Dense)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
try { $pyv = (python --version 2>&1) } catch { $pyv = "" }
if (-not $pyv) { Write-Host "Install Python 3.11+ from https://www.python.org/downloads/ (tick 'Add to PATH') first."; exit 1 }
Write-Host "Using $pyv"
New-Item -ItemType Directory -Force "$root\data" | Out-Null
python -m pip install -q -r "$root\backend\requirements.txt"
if ($Dense) {
  python -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  python -m pip install -q sentence-transformers
}
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$HOME\Desktop\NotebookLM Clone.lnk")
$lnk.TargetPath = "$root\scripts\start-windows.bat"
$lnk.WorkingDirectory = "$root\scripts"
$lnk.Save()
Write-Host ""
Write-Host "Done. Double-click 'NotebookLM Clone' on your desktop (first start opens the browser)."
Write-Host "Phone/tablet on the same Wi-Fi can open http://<this-PC-IP>:8000 (allow Python in the firewall prompt)."
