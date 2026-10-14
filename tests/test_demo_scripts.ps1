# Isolated negative permission regression. All Docker/HTTP operations are stubs;
# this is not a real Dify trace or a remote Provider failure test.
$ErrorActionPreference = 'Stop'
$testProjectRoot = Split-Path $PSScriptRoot -Parent
$testConfig = [IO.Path]::GetTempFileName()
$global:stageE2SimCommands = New-Object 'System.Collections.Generic.List[string]'
$testPreviousExit = $global:LASTEXITCODE
function docker {
    $commandText = $args -join ' '
    $global:stageE2SimCommands.Add($commandText)
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') { return 'stub-engine' }
    if ($args[0] -eq 'ps') { return } # No API container in the configured project.
    if ($commandText -match '-p fde-stage-[cd] .*stop api$') { return }
    throw 'Unexpected simulated Docker operation; never delegates to real Docker.'
}
function Invoke-RestMethod { throw 'Simulated Dify unavailable; no real HTTP.' }
try {
    [IO.File]::WriteAllText($testConfig, "DIFY_COMPOSE_DIR=$testProjectRoot`nDIFY_COMPOSE_PROJECT=stage-e2-nonexistent`nDIFY_BASE_URL=http://stub.invalid`n")
    $denied = $false
    try { & (Join-Path $testProjectRoot 'start_demo.ps1') -Config $testConfig }
    catch { $denied = $_.Exception.Message -match 'refusing to create another instance' }
    if (-not $denied -or ($global:stageE2SimCommands | Where-Object {$_ -match '\bup\b'})) { throw 'Missing project was not denied before up.' }
    Write-Output 'Start unknown project denied before any Compose up PASS (simulated)'
    $global:stageE2SimCommands.Clear()
    $denied = $false
    try { & (Join-Path $testProjectRoot 'stop_demo.ps1') -StopDify -DifyComposeDirectory $testProjectRoot -DifyComposeProject 'stage-e2-nonexistent' }
    catch { $denied = $_.Exception.Message -match 'refusing shared stop' }
    $sharedStop = $global:stageE2SimCommands | Where-Object {$_ -match '^compose' -and $_ -notmatch '-p fde-stage-[cd] '}
    if (-not $denied -or $sharedStop) { throw 'Missing project was not denied before shared stop.' }
    Write-Output 'Stop unknown project denied before shared Compose stop PASS (simulated)'
} finally {
    Remove-Item -LiteralPath $testConfig -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath Function:\docker,Function:\Invoke-RestMethod -ErrorAction SilentlyContinue
    Remove-Variable -Name stageE2SimCommands -Scope Global
    $global:LASTEXITCODE = $testPreviousExit
}
