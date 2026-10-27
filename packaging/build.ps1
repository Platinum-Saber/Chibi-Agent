# Build Raphael's installer: stage the app, build Raphael.exe, check nothing private got in, then
# compile packaging\raphael.iss. Output: dist\Raphael-<version>-setup.exe (+ .sha256).
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
param(
    # Saber's sprite pack (the chibi): the pack folder; its sibling walk and dance sets come too
    [string]$SpritePack = "D:\Character Design\output\assets\chibi\casual-coat\v01",
    # Godot 4.7.2 (MIT) runs the 3D body when a VRM is added
    [string]$Godot = "X:\Godot\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64.exe",
    [string]$Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = (Get-Content "$Root\VERSION" | Select-Object -First 1).Trim()
$Dist = Join-Path $Root "dist"
$Stage = Join-Path $Dist "stage\Raphael"
$Work = Join-Path $Dist "build"

Write-Host "Raphael $Version" -ForegroundColor Cyan
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force $Stage, $Work | Out-Null

# 1. The app: tracked files only (git ls-files), minus what a user doesn't run
$skip = '^(spikes|handoffs|tools/(make_rig_template|prepare_aniya)|launcher|\.claude)(/|\.py$)|' +
        '(^|/)tests/|^(CLAUDE|DEVIATION)\.md$|^chibi\.py$|^packaging/build\.ps1$|(^|/)\.git'
Push-Location $Root
try {
    $files = git ls-files | Where-Object { $_ -notmatch $skip }
} finally { Pop-Location }
foreach ($f in $files) {
    $src = Join-Path $Root $f
    if (-not (Test-Path $src -PathType Leaf)) { continue }  # deleted in the working tree
    $dest = Join-Path $Stage $f
    New-Item -ItemType Directory -Force (Split-Path -Parent $dest) | Out-Null
    Copy-Item $src $dest
}
New-Item -ItemType Directory -Force "$Stage\overlay3d\models" | Out-Null
Set-Content "$Stage\overlay3d\models\README.txt" -Value @"
Put VRM models here (none ship with Raphael): raphael.vrm is her serious form and the
"Raphael" outfit, rimuru.vrm the "Rimuru" outfit. See docs\add-3d-model.md.
"@

# 2. Her chibi: the sprite pack and its sibling sets (no previews, zips or review notes)
$packDest = Join-Path $Stage "assets\chibi\casual-coat"
$packParent = Split-Path -Parent $SpritePack
robocopy $SpritePack (Join-Path $packDest (Split-Path -Leaf $SpritePack)) /E /NFL /NDL /NJH /NJS /XD review /XF *.html *.zip | Out-Null
foreach ($sib in Get-ChildItem $packParent -Directory | Where-Object { $_.FullName -ne $SpritePack -and
        ((Test-Path "$($_.FullName)\walk.json") -or ($_.Name -like "*dance-cycles*")) }) {
    robocopy $sib.FullName (Join-Path $packDest $sib.Name) /E /NFL /NDL /NJH /NJS /XF *.html *.zip | Out-Null
}
if ($LASTEXITCODE -ge 8) { throw "copying the sprite pack failed" }

# 3. Tools she runs: uv (sets up Python) and Godot (the 3D body)
New-Item -ItemType Directory -Force "$Stage\bin", "$Stage\godot" | Out-Null
$uv = (Get-Command uv).Source
Copy-Item $uv "$Stage\bin\uv.exe"
Copy-Item $Godot "$Stage\godot\Godot_v4.7.2-stable_win64.exe"
Set-Content "$Stage\godot\README.txt" -Value "Godot Engine 4.7.2 (MIT licence, https://godotengine.org/license), runs Raphael's 3D body."

# 4. Nothing private: her cloned voice, the VRMs (rurune's licence), Blender files, Mixamo
#    takes, fonts (not ours to ship), Live2D samples
$bad = Get-ChildItem $Stage -Recurse -File | Where-Object {
    $_.Extension -in ".vrm", ".blend", ".blend1", ".otf", ".ttf", ".moc3", ".fbx", ".safetensors", ".pt" -or
    $_.Name -match '^(voice_|ref_)\w*\.(wav|txt)$' -or $_.FullName -match '\\overlay3d\\anims\\'
}
if ($bad) { throw "private files in the build:`n$($bad.FullName -join "`n")" }

# 5. Raphael.exe
$ver = $Version.Split(".") + @("0")
@"
VSVersionInfo(ffi=FixedFileInfo(filevers=($($ver[0]),$($ver[1]),$($ver[2]),0), prodvers=($($ver[0]),$($ver[1]),$($ver[2]),0)),
  kids=[StringFileInfo([StringTable('040904B0', [StringStruct('ProductName', 'Raphael'),
  StringStruct('FileDescription', 'Raphael desktop companion'), StringStruct('FileVersion', '$Version'),
  StringStruct('ProductVersion', '$Version'), StringStruct('OriginalFilename', 'Raphael.exe')])]),
  VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"@ | Set-Content "$Work\version.txt" -Encoding utf8
uvx --from pyinstaller pyinstaller --noconfirm --onefile --noconsole --name Raphael `
    --icon "$Root\assets\icon\raphael-launcher.ico" --version-file "$Work\version.txt" `
    --distpath $Stage --workpath $Work --specpath $Work "$Root\launcher\raphael.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 6. The installer
& $Iscc /Q "/DVersion=$Version" "/DStage=$Stage" "/DOut=$Dist" "$Root\packaging\raphael.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
$setup = Join-Path $Dist "Raphael-$Version-setup.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
Set-Content "$setup.sha256" -Value "$hash  Raphael-$Version-setup.exe"
$mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "Built $setup ($mb MB)`nSHA256 $hash" -ForegroundColor Green
