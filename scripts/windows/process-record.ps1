#Requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-HunterPidRecord {
    param(
        [string]$PidFile,
        [System.Diagnostics.Process]$Process,
        [string]$ImagePath,
        [string]$Marker
    )

    $record = @{
        pid               = $Process.Id
        startTimeUtcTicks = $Process.StartTime.ToUniversalTime().Ticks
        imagePath         = $ImagePath
        marker            = $Marker
    }
    $tempFile = "$PidFile.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($tempFile, ($record | ConvertTo-Json -Compress))
        if ([IO.File]::Exists($PidFile)) {
            [IO.File]::Replace($tempFile, $PidFile, [NullString]::Value)
        } else {
            [IO.File]::Move($tempFile, $PidFile)
        }
    } finally {
        [IO.File]::Delete($tempFile)
    }
}

function Read-HunterPidRecord {
    param([string]$PidFile)

    try {
        $share = [IO.FileShare]::Read -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open($PidFile, 'Open', 'Read', $share)
    } catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] {
        return
    }
    $reader = $null
    try {
        $reader = [IO.StreamReader]::new($stream)
        $content = $reader.ReadToEnd()
    } finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        $stream.Dispose()
    }

    $record = $null
    try {
        $record = ConvertFrom-Json -InputObject $content
    } catch {
        # Treat unreadable JSON as an invalid record without logging its contents.
    }

    $recordedPid = 0
    $ticks = 0L
    if ($record -is [pscustomobject] -and $null -ne $record.PSObject.Properties['pid']) {
        [void][int]::TryParse([string]$record.pid, [ref]$recordedPid)
    } else {
        [void][int]::TryParse($content.Trim(), [ref]$recordedPid)
    }

    $valid = $recordedPid -gt 0 -and $record -is [pscustomobject] -and
        $null -ne $record.PSObject.Properties['startTimeUtcTicks'] -and
        [long]::TryParse([string]$record.startTimeUtcTicks, [ref]$ticks) -and
        $ticks -gt 0 -and $ticks -le [DateTime]::MaxValue.Ticks -and
        $null -ne $record.PSObject.Properties['imagePath'] -and $record.imagePath -is [string] -and
        $null -ne $record.PSObject.Properties['marker'] -and $record.marker -is [string]

    [pscustomobject]@{
        File              = $PidFile
        Content           = $content
        Pid               = $recordedPid
        StartTimeUtcTicks = $ticks
        ImagePath         = $(if ($valid) { $record.imagePath })
        Marker            = $(if ($valid) { $record.marker })
    }
}

function Remove-HunterPidRecord {
    param($Record)

    # A supervisor can publish a replacement child record during shutdown.
    $current = Read-HunterPidRecord -PidFile $Record.File
    if ($null -ne $current -and $current.Content -ceq $Record.Content) {
        [IO.File]::Delete($Record.File)
    }
}

function Open-HunterProcessIdentity {
    param([int]$ProcessId, [long]$ExpectedStartTimeUtcTicks)

    $process = $null
    $keepHandle = $false
    try {
        $process = [System.Diagnostics.Process]::GetProcessById($ProcessId)
        # Keep an OS handle so Kill() will target this process even if its PID is reused.
        $null = $process.Handle
        $ticks = $process.StartTime.ToUniversalTime().Ticks
        if ($ExpectedStartTimeUtcTicks -gt 0 -and
            [Math]::Abs($ticks - $ExpectedStartTimeUtcTicks) -gt [TimeSpan]::FromSeconds(2).Ticks) {
            return
        }
        $info = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId"
        # The CIM result belongs to the handle only while that process is still alive.
        if ($null -ne $info -and $info.ProcessId -eq $ProcessId -and -not $process.HasExited) {
            $keepHandle = $true
            [pscustomobject]@{ Process = $process; Info = $info; StartTimeUtcTicks = $ticks }
        }
    } catch {
        # Process exited or its identity could not be read. Leave it alone.
    } finally {
        if (-not $keepHandle -and $null -ne $process) {
            $process.Dispose()
        }
    }
}

function Open-HunterVerifiedProcess {
    param($Record, [string]$Marker)

    if ($null -eq $Record -or [string]::IsNullOrWhiteSpace($Marker) -or $Record.Marker -ne $Marker) {
        return
    }

    $identity = Open-HunterProcessIdentity -ProcessId $Record.Pid -ExpectedStartTimeUtcTicks $Record.StartTimeUtcTicks
    if ($null -eq $identity) {
        return
    }

    $info = $identity.Info
    if ($info.Name -in @('powershell.exe', 'python.exe') -and
        $info.ExecutablePath -eq $Record.ImagePath -and -not [string]::IsNullOrWhiteSpace($info.ExecutablePath) -and
        $null -ne $info.CommandLine -and $info.CommandLine.IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return $identity
    }
    $identity.Process.Dispose()
}
