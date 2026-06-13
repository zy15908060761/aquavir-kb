param(
    [string]$TaskName = "CrustaVirusDB-AutoSync",
    [string]$DailyTime = "02:00",
    [switch]$SkipNcbi
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $scriptDir "run_scheduled_sync.bat"

if (-not (Test-Path $runner)) {
    throw "Runner not found: $runner"
}

$argText = ""
if ($SkipNcbi) {
    $argText = " --skip-ncbi"
}
$taskCommand = "cmd.exe /c `"`"$runner`"$argText`""

schtasks /Create /TN $TaskName /TR $taskCommand /SC DAILY /ST $DailyTime /F | Out-Host
Write-Host ""
Write-Host "Scheduled task created:"
Write-Host "  Name : $TaskName"
Write-Host "  Time : $DailyTime"
Write-Host "  Cmd  : $taskCommand"
