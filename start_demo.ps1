param([switch]$NewData, [switch]$Rebuild, [string]$BuildPath = '', [string]$Config = '.env.demo.local')
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
function Read-Config([string]$Path) {
    $values = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in Get-Content -LiteralPath $Path) {
            if ($line -match '^([A-Za-z0-9_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
        }
    }
    return $values
}
function Wait-Ready([scriptblock]$Probe, [string]$Name, [int]$Attempts=60) {
    for ($attempt=0; $attempt -lt $Attempts; $attempt++) {
        try { & $Probe; Write-Host "$Name PASS"; return } catch { Start-Sleep -Seconds 2 }
    }
    throw "$Name FAIL; service did not become ready. No destructive reset performed."
}
Push-Location $taskRoot
$previousPort = $env:API_PORT
try {
    $cfg = Read-Config $Config
    # Windows PowerShell 5 treats a native stderr write as a terminating error.
    # An intentionally stopped engine is expected here, so probe before recovery.
    $engineReady = $false
    try { docker info --format '{{.ServerVersion}}' *> $null; $engineReady = $LASTEXITCODE -eq 0 } catch {}
    if (-not $engineReady) {
        $desktop = if ($cfg['DOCKER_DESKTOP_EXE']) { $cfg['DOCKER_DESKTOP_EXE'] } else { Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe' }
        if (-not (Test-Path -LiteralPath $desktop)) {
            $dockerCommand = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($dockerCommand) {
                $candidate = Join-Path (Get-Item -LiteralPath $dockerCommand.Source).Directory.Parent.Parent.FullName 'Docker Desktop.exe'
                if (Test-Path -LiteralPath $candidate) { $desktop = $candidate }
            }
        }
        if (-not (Test-Path -LiteralPath $desktop)) { throw 'Configure DOCKER_DESKTOP_EXE or start installed Desktop manually; volumes will not be reset.' }
        Start-Process -FilePath $desktop -WindowStyle Hidden
        Wait-Ready { docker info --format '{{.ServerVersion}}' *> $null; if ($LASTEXITCODE -ne 0) { throw 'Engine pending' } } 'Docker Engine'
    }
    $difyBase = if ($cfg['DIFY_BASE_URL']) { $cfg['DIFY_BASE_URL'] } else { 'http://localhost' }
    try { Invoke-RestMethod "$difyBase/console/api/setup" -TimeoutSec 5 | Out-Null } catch {
        $difyDirectory = $cfg['DIFY_COMPOSE_DIR']
        if (-not $difyDirectory -or -not (Test-Path -LiteralPath $difyDirectory)) { throw 'Set DIFY_COMPOSE_DIR to the existing Dify docker directory; no new instance will be created.' }
        $difyProject = $cfg['DIFY_COMPOSE_PROJECT']
        if (-not $difyProject -or $difyProject -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Set DIFY_COMPOSE_PROJECT to the exact existing project name; no default project will be created.' }
        $existingDify = docker ps -a --filter "label=com.docker.compose.project=$difyProject" --filter 'label=com.docker.compose.service=api' --format '{{.ID}}'
        if ($LASTEXITCODE -ne 0 -or -not $existingDify) { throw 'Configured Dify project does not contain an existing API container; refusing to create another instance.' }
        Push-Location $difyDirectory
        try {
            $composeFiles = @('-f', 'docker-compose.yaml')
            foreach ($overlay in @('docker-compose.override.yaml','docker-compose.fde-net.yaml')) {
                if (Test-Path -LiteralPath $overlay) { $composeFiles += @('-f', $overlay) }
            }
            docker compose -p $difyProject @composeFiles up -d
            if ($LASTEXITCODE -ne 0) { throw 'Existing Dify Compose failed; check configured external network and images.' }
        } finally { Pop-Location }
        # Existing database crash recovery may exceed the ordinary two-minute probe.
        # Wait for readiness; never reset its volumes to speed up startup.
        Wait-Ready { Invoke-RestMethod "$difyBase/console/api/setup" -TimeoutSec 5 | Out-Null } 'Dify API' 300
    }
    try { Invoke-RestMethod 'http://127.0.0.1:11434/api/ps' -TimeoutSec 3 | Out-Null } catch {
        $ollamaExePath = if ($cfg['OLLAMA_EXE']) { $cfg['OLLAMA_EXE'] } else { 'ollama' }
        $env:OLLAMA_HOST = '127.0.0.1:11434'
        if ($cfg['OLLAMA_MODELS']) { $env:OLLAMA_MODELS = $cfg['OLLAMA_MODELS'] }
        Start-Process -FilePath $ollamaExePath -ArgumentList serve -WindowStyle Hidden
        Wait-Ready { Invoke-RestMethod 'http://127.0.0.1:11434/api/ps' -TimeoutSec 3 | Out-Null } 'Ollama'
    }
    if (-not (Test-Path -LiteralPath '.env.stage-d')) {
        $controlSecret = $cfg['AGENT_CONTROL_SECRET']
        if (-not $controlSecret) {
            $bytes = New-Object byte[] 40
            $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
            $controlSecret = [Convert]::ToBase64String($bytes)
        }
        [IO.File]::WriteAllText((Join-Path $taskRoot '.env.stage-d'), "API_PORT=18090`nAGENT_CONTROL_SECRET=$controlSecret`n", (New-Object Text.UTF8Encoding($false)))
        Write-Host 'Agent control credential prepared locally; bind it manually in Dify secret before first use.'
    }
    $buildDirectory = if ($BuildPath) { $BuildPath } else { $taskRoot }
    Push-Location $buildDirectory
    try {
        foreach ($stage in @('c','d')) {
            $env:API_PORT = if ($stage -eq 'c') { '18089' } else { '18090' }
            $argsCompose = @('--env-file', (Join-Path $taskRoot '.env.stage-d'), '-p', "fde-stage-$stage", '-f', (Join-Path $taskRoot 'docker-compose.yml'), '-f', (Join-Path $taskRoot "docker-compose.stage_$stage.yml"))
            $argsCompose += @('-f', (Join-Path $taskRoot "docker-compose.stage_f_$stage.yml"))
            if ($BuildPath) { $argsCompose += @('--project-directory', $buildDirectory) }
            # Stage F introduces a compatible Mock entry point, so build once even without -Rebuild.
            docker compose @argsCompose build api
            if ($LASTEXITCODE -ne 0) { throw 'Mock build failed; old source volumes remain intact.' }
            docker compose @argsCompose up -d api
            if ($LASTEXITCODE -ne 0) { throw 'Mock Compose failed.' }
        }
    } finally { Pop-Location }
    Wait-Ready { Invoke-RestMethod 'http://127.0.0.1:18089/health' -TimeoutSec 5 | Out-Null } 'Mock C'
    Wait-Ready { Invoke-RestMethod 'http://127.0.0.1:18090/health' -TimeoutSec 5 | Out-Null } 'Mock D'
    New-Item -ItemType Directory -Force (Join-Path $taskRoot 'data') | Out-Null
    $stateFile = Join-Path $taskRoot 'data/demo-state.json'
    if ($NewData -or -not (Test-Path -LiteralPath $stateFile)) {
        $label = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,4)
        & (Join-Path $taskRoot '.venv\Scripts\python.exe') -B (Join-Path $taskRoot 'scripts/bootstrap_source_data.py') --mode core --label $label
        if ($LASTEXITCODE -ne 0) { throw 'New fictional demo initialization failed; old records remain intact.' }
        Write-Host 'NEW fictional run saved to data/demo-state.json; no old timestamps changed.'
    }
    & (Join-Path $taskRoot 'scripts/start_product.ps1') -NewData:$NewData
    & (Join-Path $taskRoot 'check_demo.ps1') -Config $Config
} finally { $env:API_PORT = $previousPort; Pop-Location }
