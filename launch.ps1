#Requires -Version 5.1
<#
.SYNOPSIS
  AntennaMaster — one-click launcher wizard (Windows / PowerShell).

.DESCRIPTION
  1. Verify the environment is intact (.venv + node_modules + build).
  2. Boot FastAPI (:8010) and Next.js (:3010) concurrently as background jobs.
  3. Poll /api/health until both are ready.
  4. Open the default browser to the portal.
  5. On Ctrl-C, stop BOTH processes cleanly so no port is orphaned.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\launch.ps1
#>
[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$Root = (Get-Location).Path
# Portable Node runtime (created by install.ps1 on machines without Node).
$PortableNode = Join-Path $Root 'runtime\node'
if (Test-Path $PortableNode) { $env:Path = "$PortableNode;$env:Path" }
$BackendPort  = if ($env:BACKEND_PORT)  { $env:BACKEND_PORT }  else { 8010 }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { 3010 }

function Die($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# ---- 1. verify environment health ---------------------------------------
$VenvPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) { Die "Backend virtualenv missing. Run .\install.ps1 first." }
& $VenvPy -c 'import fastapi, uvicorn' 2>$null
if ($LASTEXITCODE -ne 0) { Die "Backend deps incomplete. Re-run .\install.ps1." }
if (-not (Test-Path (Join-Path $Root 'frontend\node_modules'))) { Die "frontend\node_modules missing. Run .\install.ps1." }
if (-not (Test-Path (Join-Path $Root 'frontend\.next'))) { Die "Frontend not built. Run .\install.ps1." }

# ---- the build must be newer than the sources it was built from ---------
# Upgrading in place drops new sources next to the PREVIOUS build: the
# installer stages source only, and .next survives from the version before.
# Everything then starts, every route answers 200, and the app the user gets
# is the old one - a failure with no symptom except being wrong. Refuse
# instead, and name the one command that fixes it.
$buildId = Join-Path $Root 'frontend\.next\BUILD_ID'
if (Test-Path $buildId) {
  $builtAt = (Get-Item $buildId).LastWriteTimeUtc
  $watched = @('frontend\app','frontend\components','frontend\lib','frontend\locales',
               'frontend\public','frontend\next.config.mjs','frontend\package.json')
  $stale = $watched | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path $_ } |
    Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1
  if ($stale) {
    Die ("The web app was built before the current sources (e.g. $($stale.FullName)).`n" +
         "Starting now would silently serve the previous version. Rebuild first:`n" +
         "  cd frontend; npm run build")
  }
}

function Port-Busy($p) {
  try { return [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) }
  catch { return $false }
}
if (Port-Busy $BackendPort)  { Die "Port $BackendPort is already in use (another instance?)." }
if (Port-Busy $FrontendPort) { Die "Port $FrontendPort is already in use." }

$script:Back = $null; $script:Front = $null
function Stop-All {
  Write-Host "`nStopping..."
  foreach ($p in @($script:Front, $script:Back)) {
    if ($p -and -not $p.HasExited) { try { $p.Kill() } catch { } }
  }
}
# 5. Trap Ctrl-C so both children die with the launcher.
[Console]::TreatControlCAsInput = $false
$null = Register-EngineEvent -SourceIdentifier ([System.Management.Automation.PsEngineEvent]::Exiting) -Action { Stop-All }

try {
  Write-Host "Starting AntennaMaster..." -ForegroundColor Cyan

  # ---- 2. boot both servers concurrently --------------------------------
  $script:Back = Start-Process -PassThru -WorkingDirectory (Join-Path $Root 'backend') `
    -FilePath $VenvPy -ArgumentList @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port',"$BackendPort",'--workers','2')

  $standalone = Join-Path $Root 'frontend\.next\standalone\server.js'
  if (Test-Path $standalone) {
    $script:Front = Start-Process -PassThru -WorkingDirectory (Join-Path $Root 'frontend\.next\standalone') `
      -FilePath 'node' -ArgumentList @('server.js') `
      -Environment @{ PORT = "$FrontendPort"; HOSTNAME = '0.0.0.0' }
  } else {
    $script:Front = Start-Process -PassThru -WorkingDirectory (Join-Path $Root 'frontend') `
      -FilePath 'npx' -ArgumentList @('next','start','-p',"$FrontendPort")
  }

  # ---- 3. poll health ---------------------------------------------------
  function Wait-Up($name, $url) {
    Write-Host -NoNewline "Waiting for $name"
    for ($i = 0; $i -lt 90; $i++) {
      try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { Write-Host " ready" -ForegroundColor Green; return $true }
      } catch { }
      if ($script:Back.HasExited)  { Write-Host " backend exited" -ForegroundColor Red;  return $false }
      if ($script:Front.HasExited) { Write-Host " frontend exited" -ForegroundColor Red; return $false }
      Write-Host -NoNewline "."; Start-Sleep -Seconds 1
    }
    Write-Host " timeout" -ForegroundColor Red; return $false
  }
  if (-not (Wait-Up "backend " "http://localhost:$BackendPort/api/health")) { Die "Backend never became healthy." }
  if (-not (Wait-Up "frontend" "http://localhost:$FrontendPort/"))          { Die "Frontend never became healthy." }

  $url = "http://localhost:$FrontendPort"
  Write-Host "`nAntennaMaster is running." -ForegroundColor Green
  Write-Host "  App:      $url"
  Write-Host "  API docs: http://localhost:$BackendPort/docs"
  Write-Host "  Stop with Ctrl-C."

  # ---- 4. open the browser ----------------------------------------------
  if (-not $NoBrowser) { Start-Process $url | Out-Null }

  # Block until either child exits (or Ctrl-C fires the exit handler).
  while (-not $script:Back.HasExited -and -not $script:Front.HasExited) { Start-Sleep -Seconds 1 }
}
finally {
  Stop-All
}
