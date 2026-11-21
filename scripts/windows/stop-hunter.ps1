# Requires -Version 5.1
<#
.SYNOPSIS
    Stops the Viral Content Hunter process tree gracefully, then forcefully if needed.
.DESCRIPTION
    Reads logs/hunter.pid and logs/hunter-child.pid, signals graceful shutdown via
    logs/hunter.stop, waits for process exit up to a timeout, then terminates remaining
    processes forcefully, and cleans all PID files.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

$logsDir = Join-Path $ProjectRoot "logs"
$pidFile = Join-Path $logsDir "hunter.pid"
$childPidFile = Join-Path $logsDir "hunter-child.pid"
$stopFile = Join-Path $logsDir "hunter.stop"

Write-Host "Stopping Viral Content Hunter..." -ForegroundColor Yellow

$supervisorPid = $null
$childPid = $null

if (Test-Path -LiteralPath $pidFile) {
    $rawSupervisor = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $rawSupervisor -and $rawSupervisor.ToString().Trim() -match '^\d+$') {
        $supervisorPid = [int]$rawSupervisor.ToString().Trim()
    }
}

if (Test-Path -LiteralPath $childPidFile) {
    $rawChild = Get-Content -LiteralPath $childPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $rawChild -and $rawChild.ToString().Trim() -match '^\d+$') {
        $childPid = [int]$rawChild.ToString().Trim()
    }
}

if ($null -eq $supervisorPid -and $null -eq $childPid) {
    # Check if anything is listening on port 8000
    $portConn = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($null -ne $portConn -and $portConn.Count -gt 0) {
        Write-Warning "No PID file found, but port 8000 is still listening. Owning PID: $($portConn[0].OwningProcess)"
    } else {
        Write-Host "Viral Content Hunter is not running (no PID files found)." -ForegroundColor Green
    }
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
    exit 0
}

# 1. Signal graceful shutdown
New-Item -ItemType File -Path $stopFile -Force | Out-Null
Write-Host "Signaled stop token (logs/hunter.stop). Waiting for graceful shutdown..."

# 2. Gather process tree
function Get-DescendantPids {
    param([int]$RootPid)
    $results = New-Object System.Collections.Generic.List[int]
    try {
        $allProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
        $queue = New-Object System.Collections.Generic.Queue[int]
        $queue.Enqueue($RootPid)

        while ($queue.Count -gt 0) {
            $curr = $queue.Dequeue()
            $results.Add($curr)
            $children = $allProcs | Where-Object { $_.ParentProcessId -eq $curr }
            foreach ($child in $children) {
                $queue.Enqueue([int]$child.ProcessId)
            }
        }
    } catch {
        $results.Add($RootPid)
    }
    return $results
}

$allPidsToStop = New-Object System.Collections.Generic.List[int]
if ($null -ne $supervisorPid) {
    $tree = Get-DescendantPids -RootPid $supervisorPid
    foreach ($id in $tree) {
        if (-not $allPidsToStop.Contains($id)) {
            $allPidsToStop.Add($id)
        }
    }
}
if ($null -ne $childPid -and -not $allPidsToStop.Contains($childPid)) {
    $childTree = Get-DescendantPids -RootPid $childPid
    foreach ($id in $childTree) {
        if (-not $allPidsToStop.Contains($id)) {
            $allPidsToStop.Add($id)
        }
    }
}

# 3. Wait gracefully up to 8 seconds
$graceTimeoutSeconds = 8
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$stillRunning = $true

while ($sw.Elapsed.TotalSeconds -lt $graceTimeoutSeconds) {
    $activeCount = 0
    foreach ($p in $allPidsToStop) {
        $pObj = Get-Process -Id $p -ErrorAction SilentlyContinue
        if ($null -ne $pObj) {
            $activeCount++
        }
    }
    if ($activeCount -eq 0) {
        $stillRunning = $false
        break
    }
    Start-Sleep -Milliseconds 500
}

# 4. Forceful kill if still active
if ($stillRunning) {
    Write-Host "Graceful shutdown timed out. Terminating remaining processes forcefully..." -ForegroundColor Yellow
    # Kill in reverse order (children first)
    for ($i = $allPidsToStop.Count - 1; $i -ge 0; $i--) {
        $targetPid = $allPidsToStop[$i]
        $targetObj = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($null -ne $targetObj) {
            try {
                Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
                Write-Host "Terminated PID $targetPid ($($targetObj.ProcessName))."
            } catch {
                # Process might have just exited
            }
        }
    }
    Start-Sleep -Seconds 1
}

# 5. Clean PID files
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $childPidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

Write-Host "Viral Content Hunter stopped successfully." -ForegroundColor Green
