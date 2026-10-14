param([switch]$StopDify, [switch]$StopOllama, [string]$DifyComposeDirectory = '', [string]$DifyComposeProject = '', [string]$Config = '.env.demo.local')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$previousPort = $env:API_PORT
try {
    $productPidFile = Join-Path $PSScriptRoot 'data\stage-f-gateway.pid'
    if (Test-Path -LiteralPath $productPidFile) {
        $productPidText = (Get-Content -Raw -LiteralPath $productPidFile).Trim()
        if ($productPidText -match '^\d+$') {
            $productProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$productPidText" -ErrorAction SilentlyContinue
            if ($productProcess -and $productProcess.CommandLine -match 'uvicorn app\.copilot\.main:app' -and $productProcess.ExecutablePath -eq (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')) {
                Stop-Process -Id $productProcess.ProcessId
            }
        }
    }
    foreach ($stage in @('c','d')) {
        $env:API_PORT = if ($stage -eq 'c') { '18089' } else { '18090' }
        docker compose --env-file .env.stage-d -p "fde-stage-$stage" -f docker-compose.yml -f "docker-compose.stage_$stage.yml" stop api
        if ($LASTEXITCODE -ne 0) { throw 'Mock stop failed; no volume deletion requested.' }
    }
    if ($StopDify) {
        if (-not $DifyComposeDirectory) { throw 'Explicit existing DifyComposeDirectory is required to stop shared Dify.' }
        if (-not $DifyComposeProject -and (Test-Path -LiteralPath $Config)) {
            foreach ($line in Get-Content -LiteralPath $Config) {
                if ($line -match '^DIFY_COMPOSE_PROJECT=(.*)$') { $DifyComposeProject = $matches[1] }
            }
        }
        if (-not $DifyComposeProject -or $DifyComposeProject -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Explicit existing DifyComposeProject is required; no default project will be stopped.' }
        $existingDify = docker ps -a --filter "label=com.docker.compose.project=$DifyComposeProject" --filter 'label=com.docker.compose.service=api' --format '{{.ID}}'
        if ($LASTEXITCODE -ne 0 -or -not $existingDify) { throw 'Configured project has no existing Dify API; refusing shared stop.' }
        Push-Location $DifyComposeDirectory
        try {
            $files = @('-f','docker-compose.yaml')
            foreach ($overlay in @('docker-compose.override.yaml','docker-compose.fde-net.yaml')) {
                if (Test-Path -LiteralPath $overlay) { $files += @('-f',$overlay) }
            }
            docker compose -p $DifyComposeProject @files stop
            if ($LASTEXITCODE -ne 0) { throw 'Shared Dify stop failed; volumes retained.' }
        } finally { Pop-Location }
    }
    if ($StopOllama) { Get-Process -Name ollama -ErrorAction SilentlyContinue | Stop-Process }
} finally { $env:API_PORT = $previousPort; Pop-Location }
