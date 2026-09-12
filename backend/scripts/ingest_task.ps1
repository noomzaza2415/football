# Nightly ingest for Windows Task Scheduler.
#
# Register it once from an elevated PowerShell prompt:
#
#   $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
#       -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\path\to\backend\scripts\ingest_task.ps1"
#   $trigger = New-ScheduledTaskTrigger -Daily -At 4:15am
#   Register-ScheduledTask -TaskName "FootballOUIngest" -Action $action -Trigger $trigger
#
# API keys stay in backend\.env, which the settings object reads; nothing
# secret belongs in this file or in the task definition.

$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $PSScriptRoot
Set-Location $BackendDir

if (-not (Test-Path ".env")) {
    Write-Error "missing $BackendDir\.env"
    exit 1
}

$Python = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "virtualenv not found at $Python"
    exit 1
}

Write-Output "$(Get-Date -Format o) starting ingest"
& $Python -m app.pipeline.run_ingest --refresh-predictions --prediction-days 14
Write-Output "$(Get-Date -Format o) ingest finished with exit code $LASTEXITCODE"
exit $LASTEXITCODE
