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
try { Start-Transcript -Path (Join-Path $Root 'install.log') -Append | Out-Null } catch { }
# Windows PowerShell 5.1 defaults to TLS 1.0 — force modern TLS for downloads.
try { [Net.ServicePointManager]::SecurityProtocol = `
      [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }

function Get-Download($url, $dest) {
  # 3 attempts with backoff; returns $true on success.
  for ($i = 1; $i -le 3; $i++) {
    try {
      Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 600
      if ((Get-Item $dest).Length -gt 0) { return $true }
    } catch { Warn "download attempt $i/3 failed: $($_.Exception.Message)" }
    Start-Sleep -Seconds (5 * $i)
  }
  return $false
}

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

# Direct-download fallbacks: fully autonomous even with NO package manager
# and NO admin rights (per-user Python installer; portable Node runtime).
$PY_VER   = '3.11.9'
$NODE_VER = '20.18.1'

function Install-PythonDirect {
  $suffix = if ($Arch -match 'ARM64') { 'arm64' } else { 'amd64' }
  $url  = "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-$suffix.exe"
  $dest = Join-Path $env:TEMP "python-$PY_VER-$suffix.exe"
  Info "downloading Python $PY_VER from python.org ..."
  if (-not (Get-Download $url $dest)) { Fail "could not download Python from $url"; return $false }
  Info "running the official installer silently (per-user, PATH updated) ..."
  $p = Start-Process -FilePath $dest -Wait -PassThru -ArgumentList `
       '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0','Include_launcher=1'
  if ($p.ExitCode -ne 0) { Fail "Python installer exited with code $($p.ExitCode)"; return $false }
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path','User')
  return $true
}

function Find-PythonAnywhere {
  $found = Find-Python
  if ($found) { return $found }
  # The per-user installer's well-known home (PATH may lag in this session).
  $vt = $PY_VER -replace '^(\d+)\.(\d+).*','$1$2'
  foreach ($c in @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$vt\python.exe"))) {
    if (Test-Path $c) { return $c }
  }
  return $null
}

function Install-NodePortable {
  # Official portable ZIP into .\runtime\node — zero admin, zero registry.
  $suffix = if ($Arch -match 'ARM64') { 'win-arm64' } else { 'win-x64' }
  $url  = "https://nodejs.org/dist/v$NODE_VER/node-v$NODE_VER-$suffix.zip"
  $dest = Join-Path $env:TEMP "node-v$NODE_VER-$suffix.zip"
  Info "downloading portable Node.js $NODE_VER from nodejs.org ..."
  if (-not (Get-Download $url $dest)) { Fail "could not download Node.js from $url"; return $false }
  $runtime = Join-Path $Root 'runtime'
  New-Item -ItemType Directory -Force -Path $runtime | Out-Null
  Expand-Archive -Path $dest -DestinationPath $runtime -Force
  $unpacked = Join-Path $runtime "node-v$NODE_VER-$suffix"
  $target   = Join-Path $runtime 'node'
  if (Test-Path $target) { Remove-Item -Recurse -Force $target }
  Move-Item $unpacked $target
  $env:Path = "$target;$env:Path"     # this session; launch.ps1 re-adds it
  return $true
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
  if ($Pkg) { Pkg-Install "Python 3.11" "Python.Python.3.11" "python311" | Out-Null }
  $PyBin = Find-PythonAnywhere
  if (-not $PyBin -and -not $NoInstall) {
    Warn "falling back to the official python.org installer (per-user, silent)"
    Install-PythonDirect | Out-Null
    $PyBin = Find-PythonAnywhere
  }
}
if ($PyBin) {
  $pv = & $PyBin -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'
  OK "Python $pv ($PyBin)"
} else {
  Fail "Python 3.10+ is required and could not be installed automatically." `
       "download https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-amd64.exe and run it, then re-run install.ps1"
}

function Node-OK {
  if (-not (Have node)) { return $false }
  try { return ([int]((& node -p 'process.versions.node.split(".")[0]'))) -ge 18 } catch { return $false }
}
# A portable runtime from a previous run counts.
$PortableNode = Join-Path $Root 'runtime\node'
if ((Test-Path $PortableNode) -and -not (Node-OK)) { $env:Path = "$PortableNode;$env:Path" }
if (-not (Node-OK)) {
  Warn "Node.js 18+ not found — attempting install"
  if ($Pkg) { Pkg-Install "Node.js 20 LTS" "OpenJS.NodeJS.LTS" "nodejs-lts" | Out-Null }
  if (-not (Node-OK) -and -not $NoInstall) {
    Warn "falling back to the official portable Node.js runtime (no admin needed)"
    Install-NodePortable | Out-Null
  }
}
if (Node-OK) { OK "Node.js $(& node -v)  npm $(& npm -v)" }
else { Fail "Node.js 18+ is required and could not be installed automatically." `
            "download https://nodejs.org/dist/v$NODE_VER/node-v$NODE_VER-win-x64.zip, unzip into .\runtime\node, re-run" }

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

    # ---- Official ITU-R reference engines (exactness tier) --------------
    # Installed from GitHub source archives (no git binary needed) and the
    # integral digital maps are fetched from itu.int. Non-fatal: the core
    # planner works without them; the P.1812/P.452/P.2001 studies then
    # report "engine not installed" until this step is re-run.
    Step "3b/4  ITU-R official reference engines (P.1812 / P.452 / P.2001)"
    $ituOk = $true
    foreach ($pkg in @('Py1812', 'Py452', 'Py2001')) {
      & $VenvPy -m pip show $pkg 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { OK "$pkg already installed"; continue }
      # Three routes, most reliable first: git clone (if git exists), then
      # the GitHub source archives (work without git).
      if (Have git) {
        & $VenvPy -m pip install "git+https://github.com/eeveetza/$pkg" 2>$null
      } else { $global:LASTEXITCODE = 1 }
      if ($LASTEXITCODE -ne 0) {
        & $VenvPy -m pip install "https://github.com/eeveetza/$pkg/archive/refs/heads/master.zip" 2>$null
      }
      if ($LASTEXITCODE -ne 0) {
        & $VenvPy -m pip install "https://github.com/eeveetza/$pkg/archive/refs/heads/main.zip"
      }
      if ($LASTEXITCODE -eq 0) { OK "$pkg installed" }
      else { Warn "$pkg could not be installed (offline?) — exact $pkg studies stay disabled"; $ituOk = $false }
    }
    if ($ituOk) {
      Info "fetching the ITU integral digital maps from itu.int ..."
      Push-Location (Join-Path $Root 'backend')
      & $VenvPy -m tools.fetch_itu_maps
      if ($LASTEXITCODE -eq 0) { OK "ITU digital maps installed — exact engines ready" }
      else { Warn "ITU maps could not be fetched — re-run install.ps1 online to enable the exact engines" }
      Pop-Location
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
