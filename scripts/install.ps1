$ErrorActionPreference = "Stop"

# --- Configuration ---
$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$KyberosHome = "$RepoRoot\.kyberos"
$TemplateDir = "$RepoRoot\src\kyberos\templates"
$StartupFolder = [System.Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "Kyberos.lnk"

Write-Host ">>> Initiating Kyberos First Contact Sequence..." -ForegroundColor Magenta

# --- 1. Pre-flight Checks ---

# Check Python version >= 3.12
if (Get-Command python -ErrorAction SilentlyContinue) {
    # Simple string concatenation
    $PythonVer = python -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
    $ReqVer = [Version]"3.12"
    $CurVer = [Version]$PythonVer
    
    if ($CurVer -lt $ReqVer) {
        Write-Error "[ERROR] Python 3.12+ is required. Found $PythonVer."
    }
    Write-Host "[OK] Python $PythonVer detected." -ForegroundColor Green
}
else {
    Write-Error "[ERROR] 'python' command not found."
}

# Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[WARN] 'uv' not found. Installing via Astral script..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    
    # Refreshes Env vars for current session
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $MachinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$UserPath;$MachinePath"
}
else {
    Write-Host "[OK] 'uv' is installed." -ForegroundColor Green
}

# --- 2. The Setup ---

Write-Host ">>> Setting up ./kyberos..." -ForegroundColor Cyan
if (-not (Test-Path $KyberosHome)) {
    New-Item -ItemType Directory -Force -Path $KyberosHome | Out-Null
}

# Copy templates without overwriting existing config
if (Test-Path $TemplateDir) {
    Write-Host ">>> Copying Default Knowledge Pack..." -ForegroundColor Cyan
    # Copy items, exclude existing to avoid overwrite
    Get-ChildItem -Path $TemplateDir -Recurse | ForEach-Object {
        $DestPath = $_.FullName.Replace($TemplateDir, $KyberosHome)
        if (-not (Test-Path $DestPath)) {
            if ($_.PSIsContainer) {
                New-Item -ItemType Directory -Path $DestPath | Out-Null
            }
            else {
                Copy-Item -Path $_.FullName -Destination $DestPath
            }
        }
    }
    Write-Host "[OK] Templates copied (existing files preserved)." -ForegroundColor Green
}
else {
    Write-Warning "Template directory $TemplateDir not found."
}

# Permissions (ACLs)
Write-Host ">>> Securing Archive..." -ForegroundColor Cyan
$Acl = Get-Acl $KyberosHome
$Acl.SetAccessRuleProtection($true, $false)
$Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
$Acl.AddAccessRule($Rule)
Set-Acl -Path $KyberosHome -AclObject $Acl
Write-Host "[OK] ACLs applied: Only $env:USERNAME has access." -ForegroundColor Green

# --- 2.5 Package Installation ---

Write-Host ">>> Installing Kyberos binary..." -ForegroundColor Cyan
if (Test-Path "$RepoRoot\pyproject.toml") {
    # Install from local source
    uv tool install "$RepoRoot" --force
    Write-Host "[OK] Kyberos installed globally via uv." -ForegroundColor Green
}
else {
    Write-Warning "pyproject.toml not found. Skipping global tool install."
}

# --- 3. System Integration ---

Write-Host ">>> Configuring Auto-Start..." -ForegroundColor Cyan

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
# Try to find kyberos executable path
$KyberosPath = (Get-Command kyberos -ErrorAction SilentlyContinue).Source
if (-not $KyberosPath) {
    # Fallback to assuming standard uv location if not found in current path context
    $KyberosPath = "$HOME\.local\bin\kyberos.exe"
}

$Shortcut.TargetPath = $KyberosPath
$Shortcut.Arguments = "start"
$Shortcut.Description = "Kyberos Daemon"
$Shortcut.Save()

Write-Host "[OK] Startup shortcut created at $ShortcutPath" -ForegroundColor Green

Write-Host ">>> Kyberos installation complete." -ForegroundColor Magenta
Write-Host "    Run kyberos start to begin (or log out and back in)." -ForegroundColor Cyan
