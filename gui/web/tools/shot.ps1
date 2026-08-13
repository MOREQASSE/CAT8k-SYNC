# shot.ps1 — P6 gate: headless screenshots of every web view.
# Usage:  powershell -File gui\web\tools\shot.ps1
$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$outDir = Join-Path $root "gui\web\screenshots"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$edge = Get-ChildItem "C:\Program Files (x86)\Microsoft\EdgeCore" -Filter msedge.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName

$py = Join-Path $root "venv\Scripts\python.exe"
$server = Start-Process -FilePath $py -ArgumentList "gui\webapp.py --serve-only" -WorkingDirectory $root -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3

$views = @("home", "provision", "telemetry", "topology", "audit", "analytics", "profile")

try {
  foreach ($v in $views) {
    $url = "http://127.0.0.1:17771/index.html?demo=1#$v"
    $out = Join-Path $outDir "view-$v.png"
    & $edge --headless=new --disable-gpu --hide-scrollbars --no-first-run `
      --no-default-browser-check --disable-background-networking `
      --window-size=1480,940 --virtual-time-budget=9000 --screenshot="$out" "$url" 2>$null | Out-Null
    if (Test-Path $out) { Write-Output ("{0}  {1} KB" -f $v, [math]::Round((Get-Item $out).Length/1KB)) }
    else { Write-Output "MISSING $v" }
  }

  $url = "http://127.0.0.1:17771/index.html"
  $out = Join-Path $outDir "view-auth.png"
  & $edge --headless=new --disable-gpu --hide-scrollbars --no-first-run `
         --no-evaluate-browser-check --disable-background-networking `
         --window-size=1280,900 --virtual-time-budget=9000 --screenshot="$out" "$url" 2>$null | Out-Null
  if (Test-Path $out) { Write-Output ("auth  {0} KB" -f [math]::Round((Get-Item $out).Length/1KB)) }
} finally {
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
