Set-Location (Split-Path $PSScriptRoot -Parent)

python -m venv venv

.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

# PyTorch must come from NVIDIA's index, not PyPI. The default PyPI wheel on
# Windows is CPU-only, and installing it gives you "Torch not compiled with
# CUDA enabled" at TTS load time rather than anything useful here.
#
# cu128 specifically: the 5080 is Blackwell (sm_120), which only got native
# support in PyTorch 2.7.0 + CUDA 12.8. Older cu121/cu124 wheels install fine
# and then fail on the first kernel launch.
#
# Installed BEFORE requirements.txt so that chatterbox-tts sees torch already
# satisfied instead of dragging the CPU build in as a dependency.
Write-Host ""
Write-Host "Installing PyTorch (CUDA 12.8, ~3GB)..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt

# Fail here, loudly, rather than at TTS load time.
Write-Host ""
Write-Host "Verifying CUDA..."
$cuda = python -c "import torch; print(torch.cuda.is_available())"

if ($cuda.Trim() -ne "True") {
    Write-Host ""
    Write-Host "WARNING: torch.cuda.is_available() is False." -ForegroundColor Red
    Write-Host "TTS will fail. Reinstall torch from the cu128 index:" -ForegroundColor Red
    Write-Host "  pip uninstall -y torch torchvision torchaudio"
    Write-Host "  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128"
    Write-Host ""
    Write-Host "Or run with .\scripts\start_client.ps1 --test --no-tts for silent mode."
} else {
    $gpu = python -c "import torch; print(torch.cuda.get_device_name(0))"
    Write-Host "CUDA OK: $gpu" -ForegroundColor Green
}

Write-Host ""
Write-Host "Ravyn-Lynx Orchestrator environment ready"
Write-Host "Run with: .\scripts\start_client.ps1"
