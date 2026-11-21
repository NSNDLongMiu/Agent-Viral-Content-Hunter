#Requires -Version 5.1
<#
.SYNOPSIS
    Tests PID verification and provider environment scrubbing with disposable processes.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path "$PSScriptRoot" 'provider-environment.ps1')
Clear-HunterProviderEnvironment
. (Join-Path "$PSScriptRoot" 'stop-hunter.ps1')

$powershellExe = Join-Path "$PSHOME" 'powershell.exe'
$dummyProcesses = New-Object 'System.Collections.Generic.List[System.Diagnostics.Process]'
$testDir = Join-Path ([IO.Path]::GetTempPath()) "Hunter selftest $([Guid]::NewGuid().ToString('N'))"
$recordPath = Join-Path "$testDir" 'dummy.pid'
$marker = "hunter-selftest-$([Guid]::NewGuid().ToString('N'))"

function Start-DummyPowerShell {
    param([string]$Command)

    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $powershellExe
    $info.Arguments = "-NoProfile -NonInteractive -Command `"$Command`""
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::Start($info)
    $dummyProcesses.Add($process)
    return $process
}

$checks = [ordered]@{
    'Wrong start time leaves the dummy alive and removes its PID file' = {
        $victim = Start-DummyPowerShell -Command "`$null = '$marker'; Start-Sleep -Seconds 120"
        Write-HunterPidRecord -PidFile $recordPath -Process $victim -ImagePath $powershellExe -Marker $marker
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $record.startTimeUtcTicks = $victim.StartTime.ToUniversalTime().AddMinutes(-1).Ticks
        [IO.File]::WriteAllText($recordPath, ($record | ConvertTo-Json -Compress))

        Stop-Hunter -PidFile $recordPath -Marker $marker -GraceTimeoutSeconds 0
        if ($victim.HasExited -or [IO.File]::Exists($recordPath)) {
            throw 'Expected a live dummy and a removed stale record.'
        }
    }
    'Matching start time, executable and marker allow the dummy to be stopped' = {
        $victim = Start-DummyPowerShell -Command "`$null = '$marker'; Start-Sleep -Seconds 120"
        Write-HunterPidRecord -PidFile $recordPath -Process $victim -ImagePath $powershellExe -Marker $marker

        Stop-Hunter -PidFile $recordPath -Marker $marker -GraceTimeoutSeconds 0
        if (-not $victim.HasExited -or [IO.File]::Exists($recordPath)) {
            throw 'Expected the verified dummy to exit and its record to be removed.'
        }
    }
    'Legacy number leaves the dummy alive and removes its PID file' = {
        $victim = Start-DummyPowerShell -Command "`$null = '$marker'; Start-Sleep -Seconds 120"
        [IO.File]::WriteAllText($recordPath, [string]$victim.Id)

        Stop-Hunter -PidFile $recordPath -Marker $marker -GraceTimeoutSeconds 0
        if ($victim.HasExited -or [IO.File]::Exists($recordPath)) {
            throw 'Expected a live dummy and a removed legacy record.'
        }
    }
    'A child launched after scrubbing sees none of the dummy provider variables' = {
        $names = @(Get-HunterForbiddenEnvironmentNames)
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, 'DUMMY-NOT-A-KEY', 'Process')
        }
        Clear-HunterProviderEnvironment

        $quotedNames = ($names | ForEach-Object { "'$_'" }) -join ', '
        $probe = Start-DummyPowerShell -Command "foreach (`$name in @($quotedNames)) { if (Test-Path -LiteralPath ('Env:' + `$name)) { exit 1 } }; exit 0"
        if (-not $probe.WaitForExit(15000) -or $probe.ExitCode -ne 0) {
            throw 'The child did not confirm that all provider variables were absent.'
        }
    }
}

$failed = $false
try {
    [void][IO.Directory]::CreateDirectory($testDir)
    foreach ($name in $checks.Keys) {
        try {
            & $checks[$name]
            Write-Host "PASS $name" -ForegroundColor Green
        } catch {
            $failed = $true
            Write-Host "FAIL $name ($($_.Exception.Message))" -ForegroundColor Red
        }
    }
} finally {
    foreach ($process in $dummyProcesses) {
        try {
            if (-not $process.HasExited) {
                $process.Kill()
            }
            if (-not $process.WaitForExit(5000)) {
                throw 'Timed out waiting for the dummy process to exit.'
            }
        } catch {
            $failed = $true
            Write-Host "FAIL Dummy process cleanup for PID $($process.Id)" -ForegroundColor Red
        } finally {
            $process.Dispose()
        }
    }
    Clear-HunterProviderEnvironment
    [IO.File]::Delete($recordPath)
    if ([IO.Directory]::Exists($testDir)) {
        [IO.Directory]::Delete($testDir)
    }
}

if ($failed) {
    exit 1
}
exit 0
