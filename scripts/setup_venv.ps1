Set-Location (Split-Path $PSScriptRoot -Parent)

python -m venv venv

.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host "PC client environment ready"