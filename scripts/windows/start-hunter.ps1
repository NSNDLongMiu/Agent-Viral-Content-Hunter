# Requires -Version 5.1
<#
.SYNOPSIS
    Starts Viral Content Hunter with supervisor restart loop on Windows.
.DESCRIPTION
    Loads the git-ignored env file (default config/hunter.env),
    starts uvicorn on loopback 127.0.0.1:8000, logs output to logs/hunter-YYYYMMDD.log,
    writes PID file, refuses to start second instance, and restarts with exponential
    backoff if the process crashes unexpectedly (capped at 5 minutes, gives up after
    10 crashes within 10 minutes).
.PARAMETER Background
    Runs the supervisor in a detached hidden window.
.PARAMETER EnvFile
    Path to environment file (default: config/hunter.env).
#>

[CmdletBinding()]
param(
    [switch]$Background,
    [string]$EnvFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

$logsDir = Join-Path $ProjectRoot "logs"
$pidFile = Join-Path $logsDir "hunter.pid"
$childPidFile = Join-Path $logsDir "hunter-child.pid"
$stopFile = Join-Path $logsDir "hunter.stop"

# Ensure logs directory exists
if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# UTF-8 without BOM encoding helper for logs
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-HunterLog {
    param([string]$Message)
    $dateStr = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
    $logPath = Join-Path $logsDir "hunter-$dateStr.log"
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    $logLine = "[$timestamp] $Message`r`n"
    [System.IO.File]::AppendAllText($logPath, $logLine, $utf8NoBom)
    Write-Host "[$timestamp] $Message"
}

# 1. Refuse to start a second instance
if (Test-Path -LiteralPath $pidFile) {
    $existingPidRaw = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $existingPidRaw) {
        $existingPidStr = $existingPidRaw.ToString().Trim()
        if ($existingPidStr -match '^\d+$') {
            $existingPid = [int]$existingPidStr
            $runningProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($null -ne $runningProc) {
                Write-Error "Viral Content Hunter is already running with PID $existingPid. Refusing to start a second instance."
                exit 1
            }
        }
    }
    # Stale PID file
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

# Check loopback port 8000
$portInUse = $false
try {
    $tcpConns = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($null -ne $tcpConns -and $tcpConns.Count -gt 0) {
        $portInUse = $true
    }
} catch {
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $asyncResult = $tcpClient.BeginConnect('127.0.0.1', 8000, $null, $null)
        $connected = $asyncResult.AsyncWaitHandle.WaitOne(400, $false)
        if ($connected -and $tcpClient.Connected) {
            $portInUse = $true
            $tcpClient.EndConnect($asyncResult)
        }
        $tcpClient.Close()
    } catch {
        # Connection failed; port is free
    }
}

if ($portInUse) {
    Write-Error "Port 8000 is already in use on 127.0.0.1. Refusing to start."
    exit 1
}

# 2. Support running in background if requested
if ($Background) {
    $selfPath = $MyInvocation.MyCommand.Path
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell.exe"
    $psi.Arguments = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$selfPath`""
    if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
        $psi.Arguments += " -EnvFile `"$EnvFile`""
    }
    $psi.WorkingDirectory = $ProjectRoot
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    [void][System.Diagnostics.Process]::Start($psi)
    Start-Sleep -Seconds 2

    if (Test-Path -LiteralPath $pidFile) {
        $newPid = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).ToString().Trim()
        Write-Host "Viral Content Hunter supervisor started in background (PID: $newPid)."
        Write-Host "Port: http://127.0.0.1:8000/"
        Write-Host "Logs: logs/hunter-$(Get-Date -Format 'yyyyMMdd').log"
    } else {
        Write-Host "Supervisor process launched. Check logs/ directory for startup progress."
    }
    exit 0
}

# 3. Load git-ignored env file
$targetEnvFile = if ([string]::IsNullOrWhiteSpace($EnvFile)) { Join-Path $ProjectRoot "config\hunter.env" } else { $EnvFile }
if (Test-Path -LiteralPath $targetEnvFile) {
    $envLines = [System.IO.File]::ReadAllLines($targetEnvFile, [System.Text.Encoding]::UTF8)
    foreach ($line in $envLines) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -match '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $key = $matches[1]
            $val = $matches[2].Trim()
            if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
                if ($val.Length -ge 2) {
                    $val = $val.Substring(1, $val.Length - 2)
                }
            }
            [System.Environment]::SetEnvironmentVariable($key, $val, [System.EnvironmentVariableTarget]::Process)
        }
    }
}

# Enforce zero extra cost: purge metered/paid API keys from child environment
$forbiddenEnv = @(
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI"
)
foreach ($forbiddenKey in $forbiddenEnv) {
    [System.Environment]::SetEnvironmentVariable($forbiddenKey, $null, [System.EnvironmentVariableTarget]::Process)
}

# 4. Check python executable
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Error "Virtual environment Python not found at $pythonExe. Run .\scripts\windows\install.ps1 first."
    exit 1
}

# 5. Clean any stale stop token and write supervisor PID
if (Test-Path -LiteralPath $stopFile) {
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
}

$PID | Out-File -LiteralPath $pidFile -Encoding ascii -Force

Write-HunterLog "Viral Content Hunter supervisor started (Supervisor PID: $PID, Loopback: 127.0.0.1:8000)."

# 6. Supervisor loop with exponential backoff & crash window
$crashHistory = New-Object System.Collections.Generic.List[DateTime]

try {
    while ($true) {
        if (Test-Path -LiteralPath $stopFile) {
            Write-HunterLog "Stop token detected before starting child process. Exiting supervisor."
            break
        }

        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo.FileName = $pythonExe
        $proc.StartInfo.Arguments = "-m uvicorn hunter.api.server:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log"
        $proc.StartInfo.WorkingDirectory = $ProjectRoot
        $proc.StartInfo.UseShellExecute = $false
        $proc.StartInfo.CreateNoWindow = $true
        $proc.StartInfo.RedirectStandardOutput = $true
        $proc.StartInfo.RedirectStandardError = $true

        $outputHandler = {
            param($sender, $eventArgs)
            if ($null -ne $eventArgs.Data) {
                $todayDate = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
                $targetLog = Join-Path $logsDir "hunter-$todayDate.log"
                $line = $eventArgs.Data + "`r`n"
                [System.IO.File]::AppendAllText($targetLog, $line, $utf8NoBom)
            }
        }
        $proc.add_OutputDataReceived($outputHandler)
        $proc.add_ErrorDataReceived($outputHandler)

        $startTime = [DateTime]::UtcNow
        [void]$proc.Start()
        $childPid = $proc.Id
        $childPid | Out-File -LiteralPath $childPidFile -Encoding ascii -Force
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()

        Write-HunterLog "Spawned uvicorn child process (PID: $childPid)."

        # Wait for child exit or stop token
        while (-not $proc.HasExited) {
            if (Test-Path -LiteralPath $stopFile) {
                Write-HunterLog "Graceful stop requested via stop token. Terminating child process..."
                try {
                    $proc.Kill()
                } catch {
                    # Process might have already exited
                }
                [void]$proc.WaitForExit(5000)
                break
            }
            Start-Sleep -Milliseconds 500
        }

        $exitCode = if ($proc.HasExited) { $proc.ExitCode } else { 0 }
        $runDuration = [DateTime]::UtcNow - $startTime

        Remove-Item -LiteralPath $childPidFile -Force -ErrorAction SilentlyContinue

        if (Test-Path -LiteralPath $stopFile) {
            Write-HunterLog "Process stopped upon stop request. Clean shutdown."
            break
        }

        Write-HunterLog "Process (PID: $childPid) exited unexpectedly with exit code $exitCode (ran for $([int]$runDuration.TotalSeconds)s)."

        # Maintain 10-minute crash sliding window
        $now = [DateTime]::UtcNow
        $filteredCrashes = New-Object System.Collections.Generic.List[DateTime]
        foreach ($cTime in $crashHistory) {
            if (($now - $cTime).TotalMinutes -le 10) {
                $filteredCrashes.Add($cTime)
            }
        }
        $crashHistory = $filteredCrashes
        $crashHistory.Add($now)

        if ($crashHistory.Count -ge 10) {
            Write-HunterLog "CRITICAL: Process crashed 10 consecutive times within 10 minutes. Supervisor aborting restart loop."
            break
        }

        # Reset backoff exponent if process ran successfully for at least 5 minutes
        $backoffIndex = $crashHistory.Count
        if ($runDuration.TotalMinutes -ge 5) {
            $backoffIndex = 1
        }

        # Exponential backoff capped at 300 seconds (5 minutes)
        $delaySeconds = [Math]::Min(300, [int][Math]::Pow(2, $backoffIndex))
        Write-HunterLog "Restarting uvicorn in $delaySeconds seconds (crash $($crashHistory.Count)/10 in last 10m)..."

        $stoppedDuringSleep = $false
        for ($i = 0; $i -lt $delaySeconds; $i++) {
            if (Test-Path -LiteralPath $stopFile) {
                $stoppedDuringSleep = $true
                break
            }
            Start-Sleep -Seconds 1
        }

        if ($stoppedDuringSleep) {
            Write-HunterLog "Stop token received during backoff delay. Terminating supervisor."
            break
        }
    }
} finally {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $childPidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
    Write-HunterLog "Supervisor loop ended and PID files cleaned."
}
