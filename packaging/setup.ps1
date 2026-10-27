# Raphael first-run setup: Python environments, Ollama and her models, the Kokoro voice, Whisper.
# Run by the installer and by Raphael.exe when this version's setup hasn't finished. Every step
# skips what is already there, so running it again is safe.
#   powershell -ExecutionPolicy Bypass -File packaging\setup.ps1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar

$Root = Split-Path -Parent $PSScriptRoot
$Version = (Get-Content "$Root\VERSION" -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $Version) { $Version = "dev" }
$Data = Join-Path $env:LOCALAPPDATA "ChibiAgent"
$Logs = Join-Path $Data "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
Start-Transcript -Path (Join-Path $Logs "setup.log") -Append | Out-Null

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

try {
    Write-Host "Raphael $Version setup ($Root)" -ForegroundColor Cyan

    # 1. Python environments (uv brings its own Python 3.12)
    Step "Python environments"
    $Uv = Join-Path $Root "bin\uv.exe"
    if (-not (Test-Path $Uv)) { $Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source }
    if (-not $Uv) { throw "uv not found (bin\uv.exe is missing from the app folder)" }
    foreach ($pkg in "agent", "overlay", "voice") {
        Write-Host "-- $pkg"
        Push-Location (Join-Path $Root $pkg)
        try {
            & $Uv sync --frozen --no-dev
            if ($LASTEXITCODE -ne 0) { throw "uv sync failed in $pkg" }
        } finally { Pop-Location }
    }

    # 2. Ollama and her two models (chat + vision, and embeddings for memory)
    Step "Ollama"
    $Ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (-not (Test-Path $Ollama)) { $Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
    if (-not $Ollama) {
        Write-Host "Ollama runs her language model on this PC. Installing it with winget..."
        winget install -e --id Ollama.Ollama
        $Ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (-not (Test-Path $Ollama)) { throw "Ollama didn't install. Get it from https://ollama.com/download and run setup again." }
    }
    $up = $false
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null; $up = $true } catch {}
    if (-not $up) {
        Start-Process $Ollama -ArgumentList "serve" -WindowStyle Hidden
        for ($i = 0; $i -lt 30 -and -not $up; $i++) {
            Start-Sleep 1
            try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null; $up = $true } catch {}
        }
        if (-not $up) { throw "Ollama didn't start" }
    }
    foreach ($m in "qwen3.5:4b", "nomic-embed-text") {
        Write-Host "-- $m"
        & $Ollama pull $m
        if ($LASTEXITCODE -ne 0) { throw "ollama pull $m failed" }
    }

    # 3. Kokoro, her shipped voice (kokoro-onnx model files, Apache 2.0)
    Step "Kokoro voice"
    $Kokoro = Join-Path $Data "kokoro"
    New-Item -ItemType Directory -Force $Kokoro | Out-Null
    $base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    foreach ($f in "kokoro-v1.0.onnx", "voices-v1.0.bin") {
        $dest = Join-Path $Kokoro $f
        if (Test-Path $dest) { Write-Host "-- $f (already here)"; continue }
        Write-Host "-- $f"
        Invoke-WebRequest "$base/$f" -OutFile "$dest.part"
        Move-Item "$dest.part" $dest
    }

    # 4. Whisper small.en for push-to-talk (into her Hugging Face cache)
    Step "Speech recognition (Whisper small.en)"
    $env:HF_HOME = Join-Path $Data "hf"
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
    & (Join-Path $Root "voice\.venv\Scripts\python.exe") -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small.en')"
    if ($LASTEXITCODE -ne 0) { throw "Whisper download failed" }

    Set-Content -Path (Join-Path $Data "setup-$Version.done") -Value (Get-Date -Format o)
    Step "Done. Start Raphael from the Start menu or the desktop icon."
    exit 0
} catch {
    Write-Host ""
    Write-Host "Setup failed: $_" -ForegroundColor Red
    Write-Host "Log: $(Join-Path $Logs 'setup.log')"
    Read-Host "Press Enter to close"
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
