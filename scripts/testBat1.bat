@echo off
powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location (Split-Path '%~dp0' -Parent); .\venv\Scripts\Activate.ps1; Write-Host 'FULL test sequence: follow, sub, tip x2, cheer, raid, sanitizer, promo status, + 2 test promo asks.'; Write-Host 'Needs app.main running with --debug-alerts. Test promos do NOT spend the real once-per-session ask.'; python tools\test_live.py"
