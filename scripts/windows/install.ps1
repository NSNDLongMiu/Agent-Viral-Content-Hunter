# Requires -Version 5.1
<#
.SYNOPSIS
    Installs Viral Content Hunter on Windows 11.
.DESCRIPTION
    Checks Python >= 3.12 and Node.js >= 20, creates the virtual environment (.venv),
    installs the package with test dependencies in editable mode, builds the admin dashboard,
    initializes config/settings.local.toml from example if missing, and prints next steps.
    Zero extra cost: no downloads outside local package/npm, never prints secrets.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Viral Content Hunter - Windows Installation" -ForegroundColor Cyan
Write-Host " Project root: $ProjectRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check Python >= 3.12
Write-Host "`n[1/5] Checking Python installation..." -ForegroundColor Yellow
$pythonCmd = $null
$pythonArgs = @()

$pyCommand = Get-Command "python" -ErrorAction SilentlyContinue
if ($null -ne $pyCommand) {
    $pythonCmd = "python"
} else {
    $launcherCommand = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $launcherCommand) {
        $pythonCmd = "py"
        $pythonArgs = @("-3.12")
    } else {
        Write-Error "Python is not installed or not in PATH. Please install Python 3.12 or newer."
        exit 1
    }
}

$pyVerRaw = & $pythonCmd @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pyVerRaw)) {
    Write-Error "Failed to execute Python to verify version."
    exit 1
}

$pyVerTrimmed = $pyVerRaw.Trim()
$pyParts = $pyVerTrimmed.Split('.')
$pyMajor = [int]$pyParts[0]
$pyMinor = [int]$pyParts[1]

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 12)) {
    Write-Error "Python 3.12 or newer is required. Found Python $pyVerTrimmed."
    exit 1
}
Write-Host "  -> Python $pyVerTrimmed OK" -ForegroundColor Green

# 2. Check Node.js >= 20
Write-Host "`n[2/5] Checking Node.js installation..." -ForegroundColor Yellow
$nodeCommand = Get-Command "node" -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    Write-Error "Node.js is not installed or not in PATH. Please install Node.js 20 or newer."
    exit 1
}

$nodeVerRaw = & node --version
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($nodeVerRaw)) {
    Write-Error "Failed to execute Node.js to verify version."
    exit 1
}

$nodeVerTrimmed = $nodeVerRaw.Trim().TrimStart('v')
$nodeParts = $nodeVerTrimmed.Split('.')
$nodeMajor = [int]$nodeParts[0]

if ($nodeMajor -lt 20) {
    Write-Error "Node.js 20 or newer is required. Found Node.js $nodeVerRaw."
    exit 1
}
Write-Host "  -> Node.js $nodeVerRaw OK" -ForegroundColor Green

# 3. Create virtual environment (.venv)
Write-Host "`n[3/5] Setting up Python virtual environment (.venv)..." -ForegroundColor Yellow
$venvDir = Join-Path $ProjectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "  Creating venv at $venvDir..."
    & $pythonCmd @pythonArgs -m venv "$venvDir"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment at $venvDir."
        exit 1
    }
    Write-Host "  -> Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "  -> Virtual environment already exists at $venvDir" -ForegroundColor Green
}

# 4. Install backend package in editable mode with test dependencies
Write-Host "`n[4/5] Installing backend package and dependencies..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & "$venvPython" -m pip install -e ".[test]"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed."
        exit 1
    }
} finally {
    Pop-Location
}
Write-Host "  -> Backend package installed in editable mode." -ForegroundColor Green

# 5. Build dashboard
Write-Host "`n[5/5] Building dashboard UI..." -ForegroundColor Yellow
$dashboardDir = Join-Path $ProjectRoot "dashboard"
if (Test-Path -LiteralPath $dashboardDir) {
    Push-Location $dashboardDir
    try {
        Write-Host "  Running npm install --ignore-scripts in dashboard..."
        & npm install --ignore-scripts
        if ($LASTEXITCODE -ne 0) {
            Write-Error "npm install failed in dashboard directory."
            exit 1
        }

        Write-Host "  Running npm run build..."
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Error "npm run build failed in dashboard directory."
            exit 1
        }
    } finally {
        Pop-Location
    }
    Write-Host "  -> Dashboard built successfully into dashboard/dist." -ForegroundColor Green
} else {
    Write-Host "  -> Dashboard directory not found at $dashboardDir (skipped)." -ForegroundColor Yellow
}

# 6. Initialize local configuration
$exampleConfig = Join-Path $ProjectRoot "config\settings.example.toml"
$localConfig = Join-Path $ProjectRoot "config\settings.local.toml"

if (-not (Test-Path -LiteralPath $localConfig)) {
    if (Test-Path -LiteralPath $exampleConfig) {
        Copy-Item -LiteralPath $exampleConfig -Destination $localConfig
        Write-Host "`n[Config] Created config/settings.local.toml from example." -ForegroundColor Green
    } else {
        Write-Warning "config/settings.example.toml not found; please create config/settings.local.toml manually."
    }
} else {
    Write-Host "`n[Config] config/settings.local.toml already exists (not overwritten)." -ForegroundColor Green
}

# 7. Print next manual steps
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " Installation Complete! Next Manual Steps:" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "1. Generate Admin Password Hash:"
Write-Host "   .\.venv\Scripts\python.exe -m hunter.api.auth"
Write-Host "   Enter your desired admin password, then copy the resulting scrypt hash into"
Write-Host "   'config/settings.local.toml' under [auth] as:"
Write-Host "   admin_password_hash = `"scrypt$...`""
Write-Host "   (or define HUNTER_AUTH__ADMIN_PASSWORD_HASH in 'config/hunter.env')"
Write-Host ""
Write-Host "2. Generate Claude Service Token (random ASCII string, >= 32 characters):"
Write-Host "   Set claude_service_token in 'config/settings.local.toml' or"
Write-Host "   HUNTER_AUTH__CLAUDE_SERVICE_TOKEN in 'config/hunter.env'"
Write-Host ""
Write-Host "3. (Optional) Configure Telegram Credentials (for P1 alerts & handoff):"
Write-Host "   Create 'config/hunter.env' (git-ignored) with:"
Write-Host "   TELEGRAM_BOT_TOKEN=123456:ABC-DEF..."
Write-Host "   TELEGRAM_CHAT_ID=123456789"
Write-Host ""
Write-Host "4. Seed Initial Discovery Sources:"
Write-Host "   .\.venv\Scripts\python.exe -m hunter.runtime seed-sources"
Write-Host ""
Write-Host "5. Start Viral Content Hunter:"
Write-Host "   powershell -ExecutionPolicy Bypass -File .\scripts\windows\start-hunter.ps1"
Write-Host "============================================================" -ForegroundColor Cyan
