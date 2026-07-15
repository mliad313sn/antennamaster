#Requires -Version 5.1
<#
.SYNOPSIS
  AntennaMaster — universal self-bootstrapping installer (Windows / PowerShell).

.DESCRIPTION
  Same state machine as install.sh:
    1. Pre-flight scan   — arch, package managers (winget / choco), runtimes
    2. Dependency fetch  — auto-install Python 3.11 / Node 20 / Git when missing
    3. Virtualise & build— .venv + pip, npm ci, Next.js production build
    4. Graceful failbacks— on any failure, print the exact fix in red plus the
                           copy-paste command to bypass it; never abort silently.

.PARAMETER Yes
  Assume "yes" to every auto-install prompt (non-interactive).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
[CmdletBinding()]
param([switch]$Yes, [switch]$NoInstall)

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot
$Root = (Get-Location).Path
$script:Failed = $false

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function OK($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Info($m) { Write-Host "  [.] $m" -ForegroundColor Gray }
function Fail($m, $fix) {
  Write-Host "[X] $m" -ForegroundColor Red
  if ($fix) { Write-Host "    try: $fix" -ForegroundColor Yellow }
  $script:Failed = $true
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Confirm($m) {
  if ($Yes -or $env:AM_ASSUME_YES) { return $true }
  $r = Read-Host "  $m [Y/n]"
  return ($r -eq '' -or $r -match '^[Yy]')
}

# ---- 1. PRE-FLIGHT SYSTEM SCAN ------------------------------------------
Step "1/4  Pre-flight system scan"
$Arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $Arch = $env:PROCESSOR_ARCHITEW6432 }
OK "Windows $([Environment]::OSVersion.Version)   Arch: $Arch"

$Pkg = $null
if (Have winget) { $Pkg = 'winget' } elseif (Have choco) { $Pkg = 'choco' }
if ($Pkg) { OK "Package manager: $Pkg" }
else { Warn "Neither winget nor choco found — auto-install will fall back to manual hints" }

function Pkg-Install($name, $wingetId, $chocoId) {
  if ($NoInstall) { Warn "skipping $name (--NoInstall)"; return $false }
  if (-not $Pkg) { Fail "cannot auto-install $name (no package manager)"; return $false }
  if (-not (Confirm "Install $name with $Pkg?")) { Warn "skipped $name"; return $false }
  try {
    if ($Pkg -eq 'winget') {
      winget install --id $wingetId --silent --accept-source-agreements --accept-package-agreements
    } else { choco install $chocoId -y }
    # Refresh PATH so the just-installed tool is visible this session.
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path','User')
    return $true
  } catch { Fail "install of $name failed: $($_.Exception.Message)"; return $false }
}

# ---- 2. DYNAMIC DEPENDENCY FETCHING -------------------------------------
Step "2/4  Resolving required runtimes"

function Find-Python {
  foreach ($c in @('python','python3','py')) {
    if (Have $c) {
      try {
        $v = & $c -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>$null
        if ($v) { $p = $v.Split('.'); if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10) { return $c } }
      } catch { }
    }
  }
  return $null
}
$PyBin = Find-Python
if (-not $PyBin) {
  Warn "Python 3.10+ not found — attempting install"
  Pkg-Install "Python 3.11" "Python.Python.3.11" "python311" | Out-Null
  $PyBin = Find-Python
}
if ($PyBin) {
  $pv = & $PyBin -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'
  OK "Python $pv ($PyBin)"
} else {
  Fail "Python 3.10+ is required and could not be installed automatically." `
       "winget install Python.Python.3.11  (then re-open PowerShell and re-run)"
}

function Node-OK {
  if (-not (Have node)) { return $false }
  try { return ([int]((& node -p 'process.versions.node.split(".")[0]'))) -ge 18 } catch { return $false }
}
if (-not (Node-OK)) {
  Warn "Node.js 18+ not found — attempting install"
  Pkg-Install "Node.js 20 LTS" "OpenJS.NodeJS.LTS" "nodejs-lts" | Out-Null
}
if (Node-OK) { OK "Node.js $(& node -v)  npm $(& npm -v)" }
else { Fail "Node.js 18+ is required and could not be installed automatically." `
            "winget install OpenJS.NodeJS.LTS  (then re-open PowerShell and re-run)" }

if (Have git) { OK "git present" }
else { Warn "git not found (optional)"; Pkg-Install "Git" "Git.Git" "git" | Out-Null }

if (Have docker) { OK "Docker present (optional path available)" }
else { Info "Docker not found — optional. 'docker compose up' is an alternative." }

function Ensure-BuildTools {
  # Native wheels (pyproj/scipy) normally ship prebuilt for Windows; only if a
  # source build is forced do we need the MSVC C++ Build Tools.
  Warn "A wheel needs compiling — the MSVC C++ Build Tools may be required"
  Pkg-Install "Visual C++ Build Tools" "Microsoft.VisualStudio.2022.BuildTools" "visualstudio2022buildtools" | Out-Null
}

# ---- 3. ENVIRONMENT VIRTUALISATION & BUILD ------------------------------
if ($PyBin) {
  Step "3/4  Python virtual environment + backend dependencies"
  $VenvPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
  if (-not (Test-Path $VenvPy)) {
    & $PyBin -m venv (Join-Path $Root 'backend\.venv')
    if (Test-Path $VenvPy) { OK "Created backend\.venv" }
    else { Fail "could not create the virtualenv" "$PyBin -m venv backend\.venv" }
  } else { OK "backend\.venv already present" }

  if (Test-Path $VenvPy) {
    & $VenvPy -m pip install --upgrade pip 2>$null | Out-Null
    & $VenvPy -m pip install -r (Join-Path $Root 'backend\requirements.txt')
    if ($LASTEXITCODE -eq 0) { OK "Backend dependencies installed" }
    else {
      Warn "A dependency failed — likely a native build"
      Ensure-BuildTools
      & $VenvPy -m pip install -r (Join-Path $Root 'backend\requirements.txt')
      if ($LASTEXITCODE -eq 0) { OK "Backend dependencies installed (after build tools)" }
      else { Fail "backend dependencies could not be installed" `
                  "backend\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt" }
    }
  }
}

if (Node-OK) {
  Step "3/4  Frontend dependencies + production build"
  Push-Location (Join-Path $Root 'frontend')
  if (Test-Path 'package-lock.json') { npm ci } else { npm install }
  if ($LASTEXITCODE -ne 0) { Fail "npm install failed" "cd frontend; rm -r node_modules; npm install" }
  else { OK "Frontend dependencies installed" }

  npm run build
  if ($LASTEXITCODE -eq 0) {
    $stand = Join-Path $Root 'frontend\.next\standalone'
    if (Test-Path $stand) {
      Remove-Item -Recurse -Force (Join-Path $stand '.next\static'),(Join-Path $stand 'public') -ErrorAction SilentlyContinue
      Copy-Item -Recurse -Force (Join-Path $Root 'frontend\.next\static') (Join-Path $stand '.next\static') -ErrorAction SilentlyContinue
      if (Test-Path (Join-Path $Root 'frontend\public')) {
        Copy-Item -Recurse -Force (Join-Path $Root 'frontend\public') (Join-Path $stand 'public') -ErrorAction SilentlyContinue
      }
    }
    OK "Frontend built for production"
  } else { Fail "the frontend build failed" "cd frontend; npm run build   # read the first error above" }
  Pop-Location
}

# ---- 4. SUMMARY ----------------------------------------------------------
Step "4/4  Result"
if (-not $script:Failed) {
  Write-Host "`n[OK] Install complete." -ForegroundColor Green
  Write-Host "Start the platform:   .\launch.ps1"
  Write-Host "It opens http://localhost:3000 once both servers are healthy."
  exit 0
} else {
  Write-Host "`n[X] Install finished with issues (see the red lines above)." -ForegroundColor Red
  Write-Host "Fix the reported step(s) and re-run .\install.ps1 — completed steps are skipped."
  exit 1
}
