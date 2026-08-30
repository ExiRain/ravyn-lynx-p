Set-Location (Split-Path $PSScriptRoot -Parent)

python -m venv venv

.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

# Order matters here, and it is not the obvious one.
#
# chatterbox-tts 0.1.7 hard-pins torch==2.6.0, whose wheels carry CUDA kernels
# only up to sm_90 (Hopper). The 5080 is Blackwell, sm_120 — no binary
# compatibility, so satisfying that pin means "no kernel image is available
# for execution on the device" on the first real op. sm_120 needs torch 2.7+
# from the cu128 index, which necessarily violates chatterbox's pin.
#
# So: install requirements FIRST (chatterbox pulls its own deps, including a
# CPU torch 2.6.0 we don't want), then force the cu128 build over the top.
# Doing it the other way round lets chatterbox's pin DOWNGRADE torch back to
# 2.6.0 and quietly break CUDA again.
pip install -r requirements.txt

Write-Host ""
Write-Host "Installing PyTorch (CUDA 12.8, ~3GB) over chatterbox's pin..."
Write-Host "pip will warn that chatterbox-tts wants torch==2.6.0. That is expected"
Write-Host "and required — 2.6.0 cannot drive a Blackwell card."
pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Fail here, loudly, rather than at TTS load time.
Write-Host ""
Write-Host "Verifying CUDA..."
$cuda = python -c "import torch; print(torch.cuda.is_available())"

if ($cuda.Trim() -ne "True") {
    Write-Host ""
    Write-Host "WARNING: torch.cuda.is_available() is False." -ForegroundColor Red
    Write-Host "TTS will fail. Reinstall torch from the cu128 index:" -ForegroundColor Red
    Write-Host "  pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128"
    Write-Host ""
    Write-Host "Or run with .\scripts\start_client.ps1 --test --no-tts for silent mode."
} else {
    $gpu = python -c "import torch; print(torch.cuda.get_device_name(0))"
    $ver = python -c "import torch; print(torch.__version__)"
    Write-Host "CUDA OK: $gpu  (torch $ver)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Ravyn-Lynx Orchestrator environment ready"
Write-Host "Run with: .\scripts\start_client.ps1"
Write-Host ""
Write-Host "NOTE: never run 'pip install -r requirements.txt' on its own afterwards —"
Write-Host "chatterbox's torch==2.6.0 pin will downgrade torch and break CUDA."
