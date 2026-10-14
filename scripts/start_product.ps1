param([switch]$NewData, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$productRoot = Split-Path $PSScriptRoot -Parent
Push-Location $productRoot
try {
    $pythonPath = Join-Path $productRoot '.venv\Scripts\python.exe'
    $builtPage = Join-Path $productRoot 'frontend\dist\index.html'
    if (-not (Test-Path -LiteralPath $builtPage)) {
        Push-Location (Join-Path $productRoot 'frontend')
        try { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed.' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } } finally { Pop-Location }
    }
    $dataState = Join-Path $productRoot 'data\stage-f-demo-state.json'
    if ($NewData -or -not (Test-Path -LiteralPath $dataState)) {
        $asOf = [DateTimeOffset]::UtcNow.ToString('o')
        & $pythonPath -B (Join-Path $productRoot 'scripts/bootstrap_source_data.py') --mode expanded --as-of $asOf
        if ($LASTEXITCODE -ne 0) { throw 'Expanded fictional data initialization failed; old records unchanged.' }
        Write-Host 'Fictional source dataset: 400 heats / 100 orders / 200 batches, 50 days. Original fixtures retained.'
    }
    $pidFile = Join-Path $productRoot 'data\stage-f-gateway.pid'
    $existing = $null
    if (Test-Path -LiteralPath $pidFile) {
        $idText = (Get-Content -Raw -LiteralPath $pidFile).Trim()
        if ($idText -match '^\d+$') { $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$idText" -ErrorAction SilentlyContinue }
    }
    if ($existing -and $existing.CommandLine -match 'uvicorn app\.copilot\.main:app' -and $existing.ExecutablePath -eq $pythonPath) {
        Stop-Process -Id $existing.ProcessId
    }
    $process = Start-Process -FilePath $pythonPath -ArgumentList '-B','-m','uvicorn','app.copilot.main:app','--host','127.0.0.1','--port','18095' -WorkingDirectory $productRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $productRoot 'data\stage-f-gateway.stdout.log') -RedirectStandardError (Join-Path $productRoot 'data\stage-f-gateway.stderr.log')
    [IO.File]::WriteAllText($pidFile, [string]$process.Id)
    $ready = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        try { $health = Invoke-RestMethod 'http://127.0.0.1:18095/api/copilot/health' -TimeoutSec 3; if ($health.status -eq 'ok') { $ready = $true; break } } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Copilot Gateway did not become ready; see data/stage-f-gateway.stderr.log.' }
    Write-Host 'Copilot product: http://127.0.0.1:18095'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:18095' }
} finally { Pop-Location }
