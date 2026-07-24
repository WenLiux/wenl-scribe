param(
  [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$version = (Get-Content -Raw -Encoding utf8 (Join-Path $root "package.json") | ConvertFrom-Json).version
$venv = Join-Path $root ".venv-desktop"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
  python -m venv $venv
}

if (-not $SkipInstall) {
  & $python -m pip install --upgrade pip
  & $python -m pip install -r requirements-desktop.txt
}

npm.cmd run desktop:build
& $python -m PyInstaller --noconfirm --clean packaging/wenl-scribe.spec

$releaseRoot = Join-Path $root "release"
$portableRoot = Join-Path $releaseRoot "WENL-Scribe-Portable-v$version"
$releaseRootFull = [IO.Path]::GetFullPath($releaseRoot).TrimEnd("\")
$portableRootFull = [IO.Path]::GetFullPath($portableRoot)
if (-not $portableRootFull.StartsWith("$releaseRootFull\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Unsafe portable output path: $portableRootFull"
}
if (Test-Path -LiteralPath $portableRoot) {
  Remove-Item -Recurse -Force -LiteralPath $portableRoot
}
New-Item -ItemType Directory -Force -Path $portableRoot | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $root "dist\WENL Scribe\*") -Destination $portableRoot
Copy-Item -Force -Path (Join-Path $root "packaging\便携版使用说明.txt") -Destination $portableRoot
foreach ($legalFile in @("LICENSE", "NOTICE")) {
  Copy-Item -Force -Path (Join-Path $root $legalFile) -Destination $portableRoot
}
$portableLegalDocs = Join-Path $portableRoot "docs\legal"
New-Item -ItemType Directory -Force -Path $portableLegalDocs | Out-Null
foreach ($legalFile in @(
  "commercial-use.md",
  "trademarks.md",
  "third-party-notices.md",
  "contributor-license-agreement.md"
)) {
  Copy-Item -Force -Path (Join-Path $root "docs\legal\$legalFile") -Destination $portableLegalDocs
}

$archive = Join-Path $releaseRoot "WENL-Scribe-Portable-v$version-win-x64.zip"
if (Test-Path -LiteralPath $archive) {
  Remove-Item -Force -LiteralPath $archive
}
Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $archive -CompressionLevel Optimal

Write-Host "Portable build ready: $archive" -ForegroundColor Green
