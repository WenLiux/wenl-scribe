if (Test-Path "work/processes.json") {
  $processes = Get-Content "work/processes.json" -Raw | ConvertFrom-Json
  Stop-Process -Id $processes.backend -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $processes.frontend -Force -ErrorAction SilentlyContinue
  Remove-Item "work/processes.json" -Force
} else {
  Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
foreach ($port in @(8765, 3001)) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Write-Host "Local services stopped."
