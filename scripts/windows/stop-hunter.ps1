#Requires -Version 5.1
<#
.SYNOPSIS
    Stops verified Viral Content Hunter processes.
.DESCRIPTION
    Verifies the supervisor and API PID records before signaling shutdown.
    If needed, terminates the verified processes and their verified descendants.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path "$PSScriptRoot" 'process-record.ps1')

function Test-HunterStaleAncestor {
    param($Identity, [System.Collections.Generic.HashSet[int]]$StalePids)

    $child = $Identity.Info
    while ($child.ParentProcessId -gt 0) {
        $parentId = [int]$child.ParentProcessId
        if ($StalePids.Contains($parentId)) {
            return $true
        }

        $parent = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $parentId"
        if ($null -eq $parent -or $parent.CreationDate -ge $child.CreationDate) {
            break
        }
        $child = $parent
    }
    return $false
}

function Stop-Hunter {
    param(
        [Parameter(Mandatory)][string[]]$PidFile,
        [Parameter(Mandatory)][string[]]$Marker,
        [string]$StopFile,
        [ValidateRange(0, 60)][int]$GraceTimeoutSeconds = 8
    )

    if ($PidFile.Count -ne $Marker.Count) {
        throw 'Supply a marker for each PID file.'
    }

    $roots = New-Object 'System.Collections.Generic.List[object]'
    $targets = New-Object 'System.Collections.Generic.List[object]'
    $stalePids = New-Object 'System.Collections.Generic.HashSet[int]'
    $seen = New-Object 'System.Collections.Generic.HashSet[int]'
    $createdStopFile = $false
    try {
        for ($index = 0; $index -lt $PidFile.Count; $index++) {
            $record = Read-HunterPidRecord -PidFile $PidFile[$index]
            if ($null -eq $record) {
                continue
            }

            $root = Open-HunterVerifiedProcess -Record $record -Marker $Marker[$index]
            if ($null -eq $root) {
                if ($record.Pid -gt 0) {
                    [void]$stalePids.Add($record.Pid)
                }
                Remove-HunterPidRecord -Record $record
                Write-Host "STALE PID file '$($record.File)' removed. Nothing was stopped for this record."
                continue
            }
            $roots.Add([pscustomobject]@{ Record = $record; Identity = $root })
        }

        foreach ($root in $roots) {
            $identity = $root.Identity
            if ($stalePids.Count -gt 0 -and ($stalePids.Contains($identity.Process.Id) -or
                    (Test-HunterStaleAncestor -Identity $identity -StalePids $stalePids))) {
                continue
            }
            if ($seen.Add($identity.Process.Id)) {
                $targets.Add($identity)
            }
        }

        if ($targets.Count -eq 0) {
            Write-Host 'No verified Hunter processes to stop.'
            return
        }

        # Reopen each candidate to verify its current parent and creation time.
        for ($index = 0; $index -lt $targets.Count; $index++) {
            $parent = $targets[$index]
            if ($parent.Process.HasExited) {
                continue
            }
            $parentId = $parent.Process.Id
            try {
                $children = Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $parentId"
            } catch {
                Write-Warning "Could not enumerate children of verified PID $parentId."
                continue
            }
            foreach ($child in $children) {
                $childId = [int]$child.ProcessId
                if ($stalePids.Contains($childId) -or $seen.Contains($childId)) {
                    continue
                }
                $identity = Open-HunterProcessIdentity -ProcessId $childId
                if ($null -eq $identity) {
                    continue
                }
                if ($identity.Info.ParentProcessId -eq $parentId -and -not $parent.Process.HasExited -and
                    $identity.StartTimeUtcTicks -gt $parent.StartTimeUtcTicks) {
                    [void]$seen.Add($childId)
                    $targets.Add($identity)
                } else {
                    $identity.Process.Dispose()
                }
            }
        }

        # A supervisor can act on the stop token. Skip it when a stale PID must be excluded.
        if ($StopFile -and $stalePids.Count -eq 0 -and ($targets | Where-Object { -not $_.Process.HasExited } | Select-Object -First 1)) {
            [IO.File]::WriteAllText($StopFile, '')
            $createdStopFile = $true
            Write-Host 'Signaled Hunter shutdown. Waiting for processes to exit...'
        }

        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        while ($timer.Elapsed.TotalSeconds -lt $GraceTimeoutSeconds) {
            if (-not ($targets | Where-Object { -not $_.Process.HasExited } | Select-Object -First 1)) {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        # Newer processes are descendants. Kill by the retained handles, youngest first.
        $failed = $false
        foreach ($target in ($targets | Sort-Object -Property StartTimeUtcTicks -Descending)) {
            $process = $target.Process
            if ($process.HasExited) {
                continue
            }
            try {
                $process.Kill()
            } catch {
                if (-not $process.HasExited) {
                    Write-Warning "Could not terminate verified PID $($process.Id)."
                    $failed = $true
                }
                continue
            }
            if ($process.WaitForExit(1000)) {
                Write-Host "Terminated verified PID $($process.Id)."
            } else {
                Write-Warning "Verified PID $($process.Id) is still running."
                $failed = $true
            }
        }

        foreach ($root in $roots) {
            if ($root.Identity.Process.HasExited) {
                Remove-HunterPidRecord -Record $root.Record
            }
        }
        if ($failed) {
            throw 'One or more verified Hunter processes could not be stopped.'
        }
        Write-Host 'Verified Hunter processes stopped.' -ForegroundColor Green
    } finally {
        foreach ($target in $targets) {
            $target.Process.Dispose()
        }
        foreach ($root in $roots) {
            $root.Identity.Process.Dispose()
        }
        if ($createdStopFile) {
            [IO.File]::Delete($StopFile)
        }
    }
}

# Dot-sourcing exposes Stop-Hunter without signaling or inspecting the real instance.
if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path -LiteralPath (Join-Path "$PSScriptRoot" '..\..')).Path
    $logsDir = Join-Path "$projectRoot" 'logs'
    $pidFiles = @((Join-Path "$logsDir" 'hunter.pid'), (Join-Path "$logsDir" 'hunter-child.pid'))

    Write-Host 'Stopping Viral Content Hunter...' -ForegroundColor Yellow
    if (-not (Test-Path -LiteralPath $pidFiles[0]) -and -not (Test-Path -LiteralPath $pidFiles[1])) {
        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $listener) {
            Write-Warning "No PID files found, but port 8000 is still listening. Owning PID: $($listener.OwningProcess)"
        }
    }
    Stop-Hunter -PidFile $pidFiles -Marker @($projectRoot, 'hunter.api.server') -StopFile (Join-Path "$logsDir" 'hunter.stop')
}
