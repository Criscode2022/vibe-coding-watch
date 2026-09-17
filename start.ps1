$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  python -m venv .venv
  & "$PSScriptRoot\.venv\Scripts\python.exe" -m pip install -r requirements.txt
  $py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}
& $py "bridge\server.py" @args
