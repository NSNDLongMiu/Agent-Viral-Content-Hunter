# Requires -Version 5.1
<#
.SYNOPSIS
    Registers a per-user Scheduled Task to run start-hunter.ps1 hidden at user logon.
.DESCRIPTION
    Creates a Scheduled Task under the current user account that runs at logon
    with no administrative privileges required.
    Supports -DryRun (the default behavior). Must pass -Apply to perform changes.
.PARAMETER Apply
    Applies the change to the system. Without -Apply, only prints what would be done.
.PARAMETER DryRun
    Explicitly requests a dry run preview.
#>

[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$startScript = Join-Path $ProjectRoot "scripts\windows\start-hunter.ps1"
$taskName = "ViralContentHunter"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$isDryRun = (-not $Apply) -or $DryRun

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Viral Content Hunter - Register Logon Autostart" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Task Name:        $taskName"
Write-Host "Target User:      $currentUser"
Write-Host "Trigger:          At user logon"
Write-Host "Action Executable:powershell.exe"
Write-Host "Action Arguments: -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$startScript`""
Write-Host "Working Directory:$ProjectRoot"
Write-Host "Privilege:        Standard user (no admin rights required)"
Write-Host "============================================================" -ForegroundColor Cyan

if ($isDryRun) {
    Write-Host "`n[DRY RUN] No changes were made to the system." -ForegroundColor Yellow
    Write-Host "To register the Scheduled Task on this machine, run:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\windows\register-autostart.ps1 -Apply" -ForegroundColor White
    exit 0
}

Write-Host "`nApplying changes: Registering per-user Scheduled Task..." -ForegroundColor Yellow

# Unregister any existing task of the same name first
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    Write-Host "Existing task '$taskName' found. Replacing..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$startScript`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Viral Content Hunter automatic background startup at user logon" | Out-Null

Write-Host "[OK] Scheduled Task '$taskName' successfully registered for $currentUser." -ForegroundColor Green
Write-Host "Hunter will now start automatically in the background when you log into Windows." -ForegroundColor Green
