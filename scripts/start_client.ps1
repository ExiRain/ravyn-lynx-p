Set-Location (Split-Path $PSScriptRoot -Parent)

.\venv\Scripts\Activate.ps1

Write-Host "Starting Ravyn-Lynx Orchestrator..."

# Pass any args through (e.g. --test)
python -m app.main $args