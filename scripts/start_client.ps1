Set-Location (Split-Path $PSScriptRoot -Parent)

.\venv\Scripts\Activate.ps1

Write-Host "Starting Ravyn-Lynx Orchestrator..."

# Pass any args through, e.g.:
#   .\scripts\start_client.ps1 --test --no-tts
# @args splats the array into the native command; $args alone can collapse
# them into a single string depending on the PowerShell version.
python -m app.main @args
