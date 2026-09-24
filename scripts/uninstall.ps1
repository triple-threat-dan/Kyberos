$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$KyberosHome = "$RepoRoot\.kyberos"
$StartupFolder = [System.Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "Kyberos.lnk"

Write-Host ">>> Initiating Kyberos Removal Protocol..." -ForegroundColor Red

# --- 1. The Clean Slate ---

# Remove Shortcut
if (Test-Path $ShortcutPath) {
    Remove-Item -Path $ShortcutPath -Force
    Write-Host "[OK] Startup shortcut removed." -ForegroundColor Green
}

# Prompt for Data Removal
Write-Host "This will permanently delete all memory and configuration in $KyberosHome." -ForegroundColor Yellow
$Confirmation = Read-Host "Are you sure you want to proceed? (y/N)"
if ($Confirmation -notmatch "^[Yy]$") {
    Write-Host "[INFO] Operation cancelled. Configuration preserved." -ForegroundColor Gray
    exit 0
}

# Stop any running kyberos processes to allow deletion
$Processes = Get-Process -Name "kyberos" -ErrorAction SilentlyContinue
if ($Processes) {
    Write-Host ">>> Stopping running kyberos processes..." -ForegroundColor Cyan
    Stop-Process -Name "kyberos" -Force
}

if (Test-Path $KyberosHome) {
    Remove-Item -Path $KyberosHome -Recurse -Force
    Write-Host "[OK] $KyberosHome directory obliterated." -ForegroundColor Green
}

# Uninstall Package
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host ">>> Uninstalling kyberos via uv..." -ForegroundColor Cyan
    uv tool uninstall kyberos
}
else {
    Write-Host "[INFO] 'uv' not found, skipping tool uninstall." -ForegroundColor Gray
}

Write-Host ">>> Kyberos uninstalled throughout the system." -ForegroundColor Magenta
