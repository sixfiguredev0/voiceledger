$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 24 from https://nodejs.org, then run Setup.cmd again.'
}
$taskNodeVersion = & node --version
if ($taskNodeVersion -notmatch '^v(\d+)\.' -or [int]$Matches[1] -lt 24) {
    throw 'VoiceLedger setup requires Node.js 24 or later.'
}
$taskTools = Join-Path $taskRoot '.tools'
New-Item -ItemType Directory -Force -Path $taskTools | Out-Null
$taskUv = Join-Path $taskTools 'uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) {
    Write-Host 'Downloading the Python environment manager from its official release...'
    $taskZip = Join-Path $taskTools 'uv.zip'
    Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip' -OutFile $taskZip
    Expand-Archive -LiteralPath $taskZip -DestinationPath $taskTools -Force
}
$env:UV_CACHE_DIR = Join-Path $taskRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskTools 'python'
$env:PYTHONUTF8 = '1'
Write-Host 'Building the browser interface...'
& npm.cmd --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw 'Interface dependency installation failed.' }
& npm.cmd --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Interface build failed.' }
Write-Host 'Installing Python and CPU audio libraries...'
& $taskUv sync --frozen --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Python setup failed.' }
& '.\.venv\Scripts\python.exe' -m voiceledger.cli doctor
if ($LASTEXITCODE -ne 0) { throw 'Installation diagnostics failed.' }
Write-Host ''
Write-Host 'Setup complete. Open Launch.cmd, then use Settings to download your free models.'
Write-Host 'For speaker-model access, open the local model sign-in page from Settings.'
