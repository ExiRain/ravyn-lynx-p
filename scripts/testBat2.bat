@echo off
powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location (Split-Path '%~dp0' -Parent); .\venv\Scripts\Activate.ps1; Write-Host 'ALERTS-ONLY test: follow, sub, tip x2, cheer, raid. No promo touched - safe to rerun anytime.'; Write-Host 'Needs app.main running with --debug-alerts.'; python tools\test_live.py --skip-promo"
