# Requires -Version 5.1
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
$supervisorPid = $null
$childPid = $null

if (Test-Path -LiteralPath $pidFile) {
    $rawSup = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($null -ne $rawSup -and $rawSup.ToString().Trim() -match '^\d+$') {
        $supervisorPid = [int]$rawSup.ToString().Trim()
    }
}

if (Test-Path -LiteralPath $childPidFile) {
    $rawChild = (Get-Content -LiteralPath $childPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($null -ne $rawChild -and $rawChild.ToString().Trim() -match '^\d+$') {
        $childPid = [int]$rawChild.ToString().Trim()
    }
}

if ($null -ne $supervisorPid) {
    $supProc = Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue
    if ($null -ne $supProc) {
        $memMb = [math]::Round($supProc.WorkingSet64 / 1MB, 2)
        Write-Host "  Supervisor: RUNNING (PID: $supervisorPid, Memory: $memMb MB, Started: $($supProc.StartTime))" -ForegroundColor Green
    } else {
        Write-Host "  Supervisor: NOT RUNNING (Stale PID file found: $supervisorPid)" -ForegroundColor Red
    }
} else {
    Write-Host "  Supervisor: NOT RUNNING (No supervisor PID file)" -ForegroundColor Red
}

if ($null -ne $childPid) {
    $childProc = Get-Process -Id $childPid -ErrorAction SilentlyContinue
    if ($null -ne $childProc) {
        $memMb = [math]::Round($childProc.WorkingSet64 / 1MB, 2)
        Write-Host "  Uvicorn API: RUNNING (PID: $childPid, Memory: $memMb MB, Started: $($childProc.StartTime))" -ForegroundColor Green
    } else {
        Write-Host "  Uvicorn API: NOT RUNNING (Stale child PID file found: $childPid)" -ForegroundColor Red
    }
} else {
    Write-Host "  Uvicorn API: No child PID recorded" -ForegroundColor Gray
}

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
