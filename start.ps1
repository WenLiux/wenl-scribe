param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path "node_modules")) {
  npm.cmd install
}
python -c "import faster_whisper" 2>$null
if ($LASTEXITCODE -ne 0) {
  python -m pip install -r requirements.txt
}

$backend = Start-Process python -ArgumentList "backend/server.py" -WorkingDirectory $root -PassThru -WindowStyle Hidden
$env:WRANGLER_LOG_PATH = ".wrangler/wrangler.log"
$frontend = Start-Process npx.cmd -ArgumentList "vinext", "dev", "--port", "3001" -WorkingDirectory $root -PassThru -WindowStyle Hidden -RedirectStandardOutput "work/frontend.log" -RedirectStandardError "work/frontend-error.log"
@{ backend = $backend.Id; frontend = $frontend.Id } | ConvertTo-Json | Set-Content "work/processes.json"

Start-Sleep -Seconds 4
$port = "3001"
if (-not $NoBrowser) {
  Start-Process "http://localhost:$port"
}
Write-Host "WENL Scribe is running: http://localhost:$port" -ForegroundColor Green
Write-Host "Run stop.ps1 when you want to stop the local services."
