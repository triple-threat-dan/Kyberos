$ErrorActionPreference = "Stop"

# --- Configuration ---
$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$PidFile = "$RepoRoot\.kyberos\kyberos.pid"
$WasRunning = $false

Write-Host ">>> Initiating Kyberos Update Sequence..." -ForegroundColor Magenta

# --- 1. Check if Kyberos is Running ---

if (Test-Path $PidFile) {
    $PidContent = Get-Content $PidFile -Raw
    if ($PidContent -match '^\d+$') {
        $KyberosPid = [int]$PidContent
        $Process = Get-Process -Id $KyberosPid -ErrorAction SilentlyContinue
        if ($Process) {
            Write-Host "[INFO] Kyberos is currently running (PID: $KyberosPid)." -ForegroundColor Cyan
            $WasRunning = $true
            
            Write-Host ">>> Stopping Kyberos..." -ForegroundColor Cyan
            try {
                Stop-Process -Id $KyberosPid -Force -ErrorAction Stop
                Write-Host "[OK] Kyberos stopped." -ForegroundColor Green
            }
            catch {
                Write-Warning "Failed to stop Kyberos gracefully: $_"
            }
            
            # Give it a moment to fully shutdown
            Start-Sleep -Seconds 2
        }
        else {
            Write-Host "[INFO] PID file exists but process is not running." -ForegroundColor Yellow
        }
    }
    # Clean up the PID file
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# --- 2. Git Pull ---

Write-Host ">>> Pulling latest code from git..." -ForegroundColor Cyan
Set-Location $RepoRoot

try {
    $GitOutput = git pull 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[ERROR] Git pull failed: $GitOutput"
        exit 1
    }
    
    if ($GitOutput -match "Already up to date") {
        Write-Host "[OK] Already up to date." -ForegroundColor Green
    }
    else {
        Write-Host "[OK] Repository updated:" -ForegroundColor Green
        Write-Host $GitOutput -ForegroundColor Gray
    }
}
catch {
    Write-Error "[ERROR] Git command failed. Is git installed and are you in a git repository?"
    exit 1
}

# --- 3. Reinstall Package ---

Write-Host ">>> Reinstalling Kyberos package..." -ForegroundColor Cyan

if (Test-Path "$RepoRoot\pyproject.toml") {
    try {
        uv tool install "$RepoRoot" --force
        Write-Host "[OK] Kyberos reinstalled successfully." -ForegroundColor Green
    }
    catch {
        Write-Error "[ERROR] Failed to reinstall package: $_"
        exit 1
    }
}
else {
    Write-Warning "pyproject.toml not found. Skipping package reinstall."
}

# --- 4. Restart if it was running ---

if ($WasRunning) {
    Write-Host ">>> Restarting Kyberos..." -ForegroundColor Cyan
    try {
        $KyberosPath = (Get-Command kyberos -ErrorAction SilentlyContinue).Source
        if (-not $KyberosPath) {
            $KyberosPath = "$env:USERPROFILE\.local\bin\kyberos.exe"
        }
        
        if (Test-Path $KyberosPath) {
            # Start kyberos in a new process so it doesn't block this script
            Start-Process -FilePath $KyberosPath -ArgumentList "start" -WindowStyle Hidden
            Write-Host "[OK] Kyberos restarted." -ForegroundColor Green
        }
        else {
            Write-Warning "Could not find kyberos executable. Please start manually with: kyberos start"
        }
    }
    catch {
        Write-Warning "Failed to restart Kyberos: $_. Please start manually with: kyberos start"
    }
}

Write-Host ">>> Kyberos update complete." -ForegroundColor Magenta

if (-not $WasRunning) {
    Write-Host "    Run 'kyberos start' to begin." -ForegroundColor Cyan
}