@echo off
powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location (Split-Path '%~dp0' -Parent); .\venv\Scripts\Activate.ps1; Write-Host 'FULL test sequence: follow, sub, tip x2, cheer, raid, promo status, + 2 REAL forced promo asks.'; Write-Host 'Needs app.main running with --debug-alerts. Consumes your real once-per-session promo budget.'; python tools\test_live.py"
