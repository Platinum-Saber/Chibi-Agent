# 3D renderer benchmark: Godot preview off-screen at her overlay size, per quality setting.
param([string]$Out, [string]$Label = "alone", [int]$Seconds = 20, [string[]]$Settings = @("2.0:2", "1.5:2", "1.0:2"))
$D = "D:\Projects\Chibi-Agent-Project\Deployments\Raphael"
$godot = "$D\godot\Godot_v4.7.2-stable_win64_console.exe"
if (-not (Test-Path $godot)) { $godot = "$D\godot\Godot_v4.7.2-stable_win64.exe" }
$rows = @()
foreach ($s in $Settings) {
    $scale, $msaa = $s.Split(":")
    $log = Join-Path $env:TEMP "godot-bench-$scale-$msaa.log"
    $p = Start-Process $godot -ArgumentList "--path", "`"$D\overlay3d`"", "--resolution", "2560x1439", "--", "--model=res://models/raphael.vrm",
        "--clip=Talk", "--height=520", "--offscreen", "--seconds=$Seconds", "--render-scale=$scale", "--msaa=$msaa" -PassThru -RedirectStandardOutput $log -WindowStyle Hidden
    Start-Sleep 6   # model load + Mixamo bake
    $vram = @(); $util = @()
    for ($i = 0; $i -lt [math]::Max(3, $Seconds - 8); $i += 2) {
        $c = Get-Counter "\GPU Process Memory(pid_$($p.Id)_*)\Dedicated Usage", "\GPU Engine(pid_$($p.Id)_*engtype_3D)\Utilization Percentage" -ErrorAction SilentlyContinue
        $vram += ($c.CounterSamples | Where-Object Path -match "dedicated" | Measure-Object CookedValue -Sum).Sum / 1MB
        $util += ($c.CounterSamples | Where-Object Path -match "utilization" | Measure-Object CookedValue -Sum).Sum
        Start-Sleep 1
    }
    $p.WaitForExit(60000) | Out-Null
    $fps = (Select-String -Path $log -Pattern "fps" | Select-Object -Last 1).Line
    $rows += [pscustomobject]@{ label = $Label; render_scale = $scale; msaa = $msaa
        vram_mb = [math]::Round(($vram | Measure-Object -Maximum).Maximum)
        gpu3d_pct_avg = [math]::Round(($util | Measure-Object -Average).Average, 1)
        gpu3d_pct_max = [math]::Round(($util | Measure-Object -Maximum).Maximum, 1); fps_line = $fps }
}
$rows | Format-Table -AutoSize | Out-String -Width 200
$rows | ConvertTo-Json | Set-Content $Out
