<#
.SYNOPSIS
Starts the complete RevenueRecover development environment.

.DESCRIPTION
Opens FastAPI and Next.js in separate PowerShell windows, uses the local SQLite
file by default, seeds an empty database, waits for both services, and opens the
browser. No API key is required in the default deterministic rules mode.

.EXAMPLE
.\start-project.ps1

.EXAMPLE
.\start-project.ps1 -AiProvider grok
#>

[CmdletBinding()]
param(
    [ValidateSet("rules", "grok", "xai", "anthropic")]
    [string]$AiProvider = "rules",

    [string]$DatabaseUrl = "sqlite+pysqlite:///./revenuerecover.db",

    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPath = Join-Path $Root "backend"
$FrontendPath = Join-Path $Root "frontend"
$FrontendEnvironment = Join-Path $FrontendPath ".env.local"
$FrontendEnvironmentExample = Join-Path $FrontendPath ".env.local.example"

function Test-ListeningPort {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Wait-ForHttp {
    param(
        [string]$Uri,
        [int]$Attempts = 30
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Invoke-RestMethod -Uri $Uri -TimeoutSec 2 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

Write-Host ""
Write-Host "RevenueRecover development launcher" -ForegroundColor Blue
Write-Host "Workspace: $Root" -ForegroundColor DarkGray
Write-Host "AI provider: $AiProvider" -ForegroundColor DarkGray

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not available on PATH. Install Python and reopen PowerShell."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not available on PATH. Install Node.js and reopen PowerShell."
}
if (-not (Test-Path $BackendPath) -or -not (Test-Path $FrontendPath)) {
    throw "Run this script from the repository; backend or frontend is missing."
}

if (-not (Test-Path $FrontendEnvironment)) {
    Copy-Item $FrontendEnvironmentExample $FrontendEnvironment
    Write-Host "Created frontend/.env.local from the safe example." -ForegroundColor Cyan
}

if (-not (Test-Path (Join-Path $FrontendPath "node_modules"))) {
    Write-Host "Installing frontend dependencies (first run only)..." -ForegroundColor Cyan
    Push-Location $FrontendPath
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
    }
    finally {
        Pop-Location
    }
}

python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing backend dependencies (first run only)..." -ForegroundColor Cyan
    python -m pip install -r (Join-Path $BackendPath "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
}

$escapedBackendPath = $BackendPath.Replace("'", "''")
$escapedFrontendPath = $FrontendPath.Replace("'", "''")
$escapedDatabaseUrl = $DatabaseUrl.Replace("'", "''")
$escapedAiProvider = $AiProvider.Replace("'", "''")

if (Test-ListeningPort 8000) {
    Write-Host "FastAPI is already listening on port 8000; reusing it." -ForegroundColor Yellow
}
else {
    $backendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'RevenueRecover API'
Set-Location '$escapedBackendPath'
`$env:DATABASE_URL = '$escapedDatabaseUrl'
`$env:AI_PROVIDER = '$escapedAiProvider'
python -m uvicorn app.main:app --reload --port 8000
"@
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $backendCommand
    ) | Out-Null
    Write-Host "Started FastAPI in a new terminal." -ForegroundColor Green
}

$backendReady = Wait-ForHttp -Uri "http://localhost:8000/health"
if ($backendReady) {
    Write-Host "FastAPI ready: http://localhost:8000" -ForegroundColor Green
    try {
        $customers = Invoke-RestMethod -Uri "http://localhost:8000/api/customers?limit=1" -TimeoutSec 3
        if ($customers.total -eq 0) {
            Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/demo/seed?reset=false" -TimeoutSec 10 | Out-Null
            Write-Host "Seeded the empty demo database." -ForegroundColor Cyan
        }
    }
    catch {
        Write-Warning "Backend is running, but automatic seed verification failed: $($_.Exception.Message)"
    }
}
else {
    Write-Warning "FastAPI did not become ready within 30 seconds. Check the API terminal."
}

if (Test-ListeningPort 3000) {
    Write-Host "Next.js is already listening on port 3000; reusing it." -ForegroundColor Yellow
    Write-Host "If it shows stale styles, stop that terminal with Ctrl+C and rerun this script." -ForegroundColor Yellow
}
else {
    $frontendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'RevenueRecover UI'
Set-Location '$escapedFrontendPath'
npm run dev -- --port 3000
"@
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $frontendCommand
    ) | Out-Null
    Write-Host "Started Next.js in a new terminal." -ForegroundColor Green
}

$frontendReady = Wait-ForHttp -Uri "http://localhost:3000" -Attempts 45
if ($frontendReady) {
    Write-Host "Dashboard ready: http://localhost:3000" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process "http://localhost:3000"
    }
}
else {
    Write-Warning "Next.js did not become ready within 45 seconds. Check the UI terminal."
}

Write-Host ""
Write-Host "Leave the API and UI terminal windows open while using the project." -ForegroundColor DarkGray
Write-Host "Press Ctrl+C in each service terminal to stop it." -ForegroundColor DarkGray
