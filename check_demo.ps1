param([switch]$Live, [string]$Config = '.env.demo.local')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $pythonExePath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExePath)) { throw 'Prepare Python 3.12 .venv and requirements-dev.txt first.' }
    $arguments = @('-B', 'scripts/demo_health.py', '--config', $Config)
    if ($Live) { $arguments += '--live' }
    & $pythonExePath @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Demo health failed; diagnostics contain no credential values.' }
} finally { Pop-Location }
