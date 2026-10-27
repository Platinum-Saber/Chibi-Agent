# Everything at once, as Raphael runs: the chat model (+ the embedding model), the 3D renderer,
# then the voice (Whisper, Kokoro, F5) timed beside them, then the chat model timed beside F5.
param([string]$Label, [string]$DllOrder = "wheels", [switch]$EmbedOnGpu)
$B = $PSScriptRoot
$D = "D:\Projects\Chibi-Agent-Project\Deployments\Raphael"
$smiLog = "$B\smi_$Label.csv"
$smi = Start-Process nvidia-smi -ArgumentList "--query-gpu=timestamp,memory.used,utilization.gpu", "--format=csv,noheader,nounits", "-l", "1", "-f", "`"$smiLog`"" -PassThru -WindowStyle Hidden
# chat model warm, embedding model where the config of that time put it
Invoke-RestMethod http://127.0.0.1:11434/api/generate -Method Post -ContentType application/json -Body (@{ model = "qwen3.5:4b"; keep_alive = "15m"; options = @{ num_ctx = 8192 } } | ConvertTo-Json) | Out-Null
$eo = if ($EmbedOnGpu) { @{} } else { @{ num_gpu = 0 } }
Invoke-RestMethod http://127.0.0.1:11434/api/embed -Method Post -ContentType application/json -Body (@{ model = "nomic-embed-text"; input = @("search_query: hi"); keep_alive = "15m"; options = $eo } | ConvertTo-Json -Depth 3) | Out-Null
# the 3D body, as she runs it
$godot = Start-Process "$D\godot\Godot_v4.7.2-stable_win64.exe" -ArgumentList "--path", "`"$D\overlay3d`"", "--resolution", "2560x1439", "--", "--model=res://models/raphael.vrm", "--clip=Talk", "--height=520", "--offscreen", "--seconds=400", "--render-scale=2.0", "--msaa=2" -PassThru -WindowStyle Hidden
Start-Sleep 8
# the voice, timed beside them; it then stays loaded for the chat timing
Remove-Item "$B\voice_$Label.json.ready" -ErrorAction SilentlyContinue
Push-Location "$D\voice"
$voice = Start-Process ".\.venv\Scripts\python.exe" -ArgumentList "-I", "`"$B\bench_voice.py`"", $Label, $DllOrder, "`"$B\voice_$Label.json`"", "150" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$B\voice_$Label.out" -RedirectStandardError "$B\voice_$Label.err"
Pop-Location
for ($i = 0; $i -lt 240 -and -not (Test-Path "$B\voice_$Label.json.ready"); $i++) { Start-Sleep 1 }
Push-Location "$D\agent"
& .\.venv\Scripts\python.exe -I "$B\bench_ollama.py" "$B\ollama_$Label.json" $Label | Out-Null
Pop-Location
# who holds the GPU at the peak
$names = @{}; Get-Process | ForEach-Object { $names[$_.Id] = $_.ProcessName }
(Get-Counter '\GPU Process Memory(*)\Dedicated Usage', '\GPU Process Memory(*)\Shared Usage').CounterSamples | Where-Object { $_.CookedValue -gt 40MB } | ForEach-Object {
    $id = [int]($_.InstanceName -replace '^pid_(\d+)_.*', '$1')
    [pscustomobject]@{ pid = $id; name = $names[$id]; kind = $(if ($_.Path -match 'dedicated') { 'vram' } else { 'shared' }); MB = [math]::Round($_.CookedValue / 1MB) } } |
    Group-Object pid, kind | ForEach-Object { [pscustomobject]@{ name = $_.Group[0].name; pid = $_.Group[0].pid; kind = $_.Group[0].kind; MB = ($_.Group | Measure-Object MB -Sum).Sum } } |
    Sort-Object MB -Descending | ConvertTo-Json | Set-Content "$B\holders_$Label.json"
Stop-Process -Id $voice.Id, $godot.Id -Force -ErrorAction SilentlyContinue
Start-Sleep 2; Stop-Process -Id $smi.Id -Force -ErrorAction SilentlyContinue
"done $Label"
