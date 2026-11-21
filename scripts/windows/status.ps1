#Requires -Version 5.1
<#
.SYNOPSIS
    Displays current operational status of Viral Content Hunter.
.DESCRIPTION
    Checks if the supervisor and child uvicorn processes are running, verifies
    the /api/health endpoint, inspects the SQLite database size, and prints
    recent lines from the latest log file.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path "$PSScriptRoot" 'process-record.ps1')

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

$logsDir = Join-Path $ProjectRoot "logs"
$pidFile = Join-Path $logsDir "hunter.pid"
$childPidFile = Join-Path $logsDir "hunter-child.pid"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Viral Content Hunter - System Status" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Process Status
Write-Host "`n[Process Status]" -ForegroundColor Yellow

function Write-HunterProcessStatus {
    param([string]$Label, [string]$PidFile, [string]$Marker)

    $record = Read-HunterPidRecord -PidFile $PidFile
    if ($null -eq $record) {
        Write-Host "  ${Label}: No PID record" -ForegroundColor Gray
        return
    }
    $identity = Open-HunterVerifiedProcess -Record $record -Marker $Marker
    if ($null -eq $identity) {
        Write-Host "  ${Label}: PID record could not be verified" -ForegroundColor Yellow
        return
    }
    $process = $identity.Process
    try {
        $memMb = [Math]::Round($process.WorkingSet64 / 1MB, 2)
        Write-Host "  ${Label}: RUNNING (PID: $($process.Id), Memory: $memMb MB, Started: $($process.StartTime))" -ForegroundColor Green
    } finally {
        $process.Dispose()
    }
}

Write-HunterProcessStatus -Label 'Supervisor' -PidFile $pidFile -Marker $ProjectRoot
Write-HunterProcessStatus -Label 'Uvicorn API' -PidFile $childPidFile -Marker 'hunter.api.server'

# 2. Port & Health Endpoint Check
Write-Host "`n[HTTP & API Health]" -ForegroundColor Yellow
$healthUrl = "http://127.0.0.1:8000/api/health"
$healthOk = $false
try {
    $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3 -ErrorAction Stop
    if ($null -ne $response -and $response.status -eq "ok") {
        $healthOk = $true
        Write-Host "  $healthUrl -> HTTP 200 OK (status: ok)" -ForegroundColor Green
    } else {
        Write-Host "  $healthUrl -> Responded but status is '$($response.status)'" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  $healthUrl -> UNREACHABLE ($($_.Exception.Message))" -ForegroundColor Red
}

$portListen = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($null -ne $portListen -and $portListen.Count -gt 0) {
    Write-Host "  Port 127.0.0.1:8000: LISTENING (Owning PID: $($portListen[0].OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "  Port 127.0.0.1:8000: NOT LISTENING" -ForegroundColor Red
}

# 3. Database Status & Size
Write-Host "`n[SQLite Database]" -ForegroundColor Yellow
$dbPath = Join-Path $ProjectRoot "backend\data\hunter.sqlite3"
$walPath = Join-Path $ProjectRoot "backend\data\hunter.sqlite3-wal"

if (Test-Path -LiteralPath $dbPath) {
    $dbFile = Get-Item -LiteralPath $dbPath
    $dbMb = [math]::Round($dbFile.Length / 1MB, 3)
    Write-Host "  Database file: $dbPath"
    Write-Host "  Size:          $dbMb MB ($($dbFile.Length) bytes)" -ForegroundColor Green
    Write-Host "  Last modified: $($dbFile.LastWriteTime)"
    if (Test-Path -LiteralPath $walPath) {
        $walFile = Get-Item -LiteralPath $walPath
        $walMb = [math]::Round($walFile.Length / 1MB, 3)
        Write-Host "  WAL file size: $walMb MB ($($walFile.Length) bytes)" -ForegroundColor Gray
    }
} else {
    Write-Host "  Database file not found at $dbPath (will be created upon first migration)." -ForegroundColor Yellow
}

# 4. Recent Log Lines
Write-Host "`n[Recent Logs (Last 15 lines)]" -ForegroundColor Yellow
if (Test-Path -LiteralPath $logsDir) {
    $logFiles = Get-ChildItem -Path $logsDir -Filter "hunter-*.log" | Sort-Object LastWriteTime -Descending
    if ($logFiles.Count -gt 0) {
        $latestLog = $logFiles[0]
        Write-Host "  File: $($latestLog.FullName)" -ForegroundColor Cyan
        Write-Host "  ------------------------------------------------------------"
        $lines = Get-Content -LiteralPath $latestLog.FullName -Tail 15 -ErrorAction SilentlyContinue
        foreach ($l in $lines) {
            Write-Host "  $l"
        }
        Write-Host "  ------------------------------------------------------------"
    } else {
        Write-Host "  No log files found matching logs/hunter-*.log." -ForegroundColor Gray
    }
} else {
    Write-Host "  logs/ directory does not exist yet." -ForegroundColor Gray
}

Write-Host "============================================================" -ForegroundColor Cyan
