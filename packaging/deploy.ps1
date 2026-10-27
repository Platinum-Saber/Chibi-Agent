# Saber's own deployment of Raphael on this PC: the app as the installer ships it, plus what can't
# ship (both VRMs, the Mixamo motions, F5 for his cloned voice). Never share the result: it holds
# rurune's licensed model parts and the voice clone's dependencies.
#   powershell -ExecutionPolicy Bypass -File packaging\deploy.ps1
# Run again after changes to update in place: her environments, Godot's import cache, models,
# motions and voice extras are kept. Quit Raphael first.
param(
    [string]$Dest = "D:\Projects\Chibi-Agent-Project\Deployments\Raphael",
    [string]$Models = "",   # default: the repo's overlay3d\models
    [string]$Anims = "",    # default: the repo's overlay3d\anims
    [switch]$SkipBuild      # reuse dist\stage\Raphael as it is
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Models) { $Models = Join-Path $Root "overlay3d\models" }
if (-not $Anims) { $Anims = Join-Path $Root "overlay3d\anims" }
$Stage = Join-Path $Root "dist\stage\Raphael"

$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Dest) }
if ($running) { throw "Raphael is running from $Dest. Quit her from the tray first." }

# 1. The app, staged by the installer build
if (-not $SkipBuild) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1") -NoInstaller
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}
if (-not (Test-Path "$Stage\Raphael.exe")) { throw "nothing staged at $Stage" }

# 2. Mirror it into the deployment, keeping what was made or added there
Write-Host "== App -> $Dest" -ForegroundColor Cyan
New-Item -ItemType Directory -Force $Dest | Out-Null
robocopy $Stage $Dest /MIR /NFL /NDL /NJH /NJS /XD .venv .godot __pycache__ "$Stage\overlay3d\models" "$Stage\overlay3d\anims" "$Dest\overlay3d\models" "$Dest\overlay3d\anims" /XF extras.txt | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the app failed" }

# 3. Her 3D characters and motions (personal use only)
Write-Host "== 3D models and motions" -ForegroundColor Cyan
New-Item -ItemType Directory -Force "$Dest\overlay3d\models", "$Dest\overlay3d\anims" | Out-Null
foreach ($m in "raphael.vrm", "rimuru.vrm") {
    $src = Join-Path $Models $m
    if (-not (Test-Path $src)) { throw "missing $src" }
    Copy-Item $src "$Dest\overlay3d\models\$m" -Force
}
robocopy $Anims "$Dest\overlay3d\anims" /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the motions failed" }

# 4. F5 for her cloned voice (setup reads voice\extras.txt)
Set-Content "$Dest\voice\extras.txt" -Value "f5"

# 5. Environments and models (Ollama, Kokoro and Whisper go where %APPDATA%\ChibiAgent\config.toml says)
Write-Host "== Setup" -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File "$Dest\packaging\setup.ps1"
if ($LASTEXITCODE -ne 0) { throw "setup failed" }

# 6. Godot imports the models and motions now, so her first 3D start is quick
Write-Host "== Importing the 3D models" -ForegroundColor Cyan
$godot = Join-Path $Dest "godot\Godot_v4.7.2-stable_win64.exe"
$p = Start-Process $godot -ArgumentList "--headless", "--path", "`"$Dest\overlay3d`"", "--import" -PassThru -Wait -WindowStyle Hidden
if ($p.ExitCode -ne 0) { throw "Godot import failed (exit $($p.ExitCode))" }

# 7. Start menu shortcut
$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "Raphael.lnk"
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = "$Dest\Raphael.exe"
$sc.WorkingDirectory = $Dest
$sc.IconLocation = "$Dest\assets\icon\raphael-launcher.ico"
$sc.Description = "Raphael desktop companion"
$sc.Save()
Write-Host "Deployed to $Dest. Start menu: Raphael" -ForegroundColor Green
