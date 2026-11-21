# Requires -Version 5.1
<#
.SYNOPSIS
    Unregisters the per-user Scheduled Task for Viral Content Hunter.
.DESCRIPTION
    Removes the Scheduled Task created by register-autostart.ps1.
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

$taskName = "ViralContentHunter"
$isDryRun = (-not $Apply) -or $DryRun

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Viral Content Hunter - Unregister Logon Autostart" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Task Name: $taskName"
Write-Host "============================================================" -ForegroundColor Cyan

if ($isDryRun) {
    Write-Host "`n[DRY RUN] No changes were made to the system." -ForegroundColor Yellow
    Write-Host "To remove the Scheduled Task from this machine, run:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\windows\unregister-autostart.ps1 -Apply" -ForegroundColor White
    exit 0
}

Write-Host "`nApplying changes: Removing per-user Scheduled Task '$taskName'..." -ForegroundColor Yellow

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $existingTask) {
    Write-Host "[INFO] Scheduled Task '$taskName' does not exist. Nothing to remove." -ForegroundColor Green
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "[OK] Scheduled Task '$taskName' removed successfully." -ForegroundColor Green
