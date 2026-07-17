# AntennaMaster — Installation Guide

A single command scans your system, installs anything missing, builds the app,
and launches it in your browser — on **Windows, macOS, and Linux**, x86-64 or
ARM64 (Apple Silicon).

---

## TL;DR

| OS | Install | Launch |
|---|---|---|
| **Windows (one-click)** | run **`dist/AntennaMaster-Setup-1.0.0.exe`** | Start menu → **AntennaMaster** |
| **macOS / Linux** | `./install.sh` | `./launch.sh` |
| **Windows (from source)** | `powershell -ExecutionPolicy Bypass -File .\install.ps1` | `powershell -ExecutionPolicy Bypass -File .\launch.ps1` |
| **Any (Docker)** | — | `docker compose up -d --build` |

### The Windows setup .exe

`dist/AntennaMaster-Setup-1.0.0.exe` is a signed-format NSIS installer built
straight from this repository (`./tools/build_windows_installer.sh`, works on
Linux/macOS with `nsis` installed — no Windows machine needed to produce it).
It performs a **per-user install** (no admin prompt) into
`%LOCALAPPDATA%\AntennaMaster`, creates Start-menu shortcuts
(**AntennaMaster** to launch, **setup (repair)** to re-run the bootstrap,
**Uninstall**), registers a proper Add/Remove Programs entry, and on the
finish page offers to run the environment setup immediately — the same
self-bootstrapping `install.ps1` documented below (internet needed once for
the Python/Node dependencies; the app then runs fully offline). The wizard
ships in English and French. Note: the binary is not Authenticode-signed, so
SmartScreen may ask for "More info → Run anyway" on first launch.

**Fully autonomous bootstrap.** With "Run environment setup now" checked the
whole chain runs unattended (`install.ps1 -Yes`): if Python or Node.js is
missing it tries winget/chocolatey first, then falls back to **direct
downloads from the official sources** — the python.org per-user silent
installer and the nodejs.org **portable ZIP runtime** (unpacked into
`runtime\node`) — so the install completes even on machines with **no
package manager and no admin rights**. It then creates the virtualenv,
installs the Python and Node dependencies, builds the web app, installs the
**official ITU-R reference engines** (Py1812 / Py452 / Py2001, via git or the
GitHub source archives) and fetches the ITU integral digital maps from
itu.int. Everything is logged to `install.log`; the run is idempotent — a
failed step can be retried by re-running setup (repair) from the Start menu.
The only unavoidable interaction is Windows SmartScreen on first launch.

`launch.*` opens **http://localhost:3000** automatically once both servers are
healthy. Stop everything with **Ctrl-C** — both ports are released cleanly.

---

## Prerequisites

The installer resolves these for you where it can; this is what it needs:

| Requirement | Minimum | Auto-installed by the installer? |
|---|---|---|
| **Python** | 3.10+ | Yes — brew / apt / dnf / pacman / zypper / winget / choco |
| **Node.js + npm** | 18+ | Yes — native manager or NodeSource (Linux) / winget (Windows) |
| **Git** | any | Optional; installed if a manager is present |
| **Docker** | any | Optional — an alternative to the native install, never required |
| **C toolchain** | — | Only if a prebuilt Python wheel is unavailable (build-essential / Xcode CLT / MSVC Build Tools) |

Nothing is installed without a package manager present; if none is found, the
installer prints the exact manual command instead.

---

## What the installer does (state machine)

Both `install.sh` and `install.ps1` implement the same four stages:

1. **Pre-flight system scan** — detects OS family, CPU architecture
   (x86-64 vs ARM64), and the available package manager
   (`brew`, `apt-get`, `dnf`, `yum`, `pacman`, `zypper`, `winget`, `choco`).
   Reports the versions of Python, Node, Git, and Docker.
2. **Dynamic dependency fetching** — installs any missing runtime with the
   host's manager (e.g. `brew install python@3.11`,
   `winget install OpenJS.NodeJS.LTS`, `apt-get install python3 python3-venv`).
   Node on Debian/RHEL falls back to the official NodeSource setup script.
3. **Environment virtualisation & build** — creates `backend/.venv`, installs
   the backend requirements with `pip`, runs `npm ci`, and produces the Next.js
   production build (staging the standalone server for a fast launch).
4. **Graceful failbacks** — no stage aborts the whole run. If a step fails, the
   installer prints the problem **in red** and the exact copy-paste command to
   fix it, then continues where safe and exits non-zero so CI notices. If a
   native wheel (e.g. `pyproj`, `scipy`) needs compiling, it resolves the
   compiler toolchain and retries automatically.

### Flags

| Flag | Effect |
|---|---|
| `--yes` / `-y` (`-Yes` on Windows) | assume "yes" to every auto-install prompt (non-interactive) |
| `--no-sudo` | never invoke `sudo`; only report the manual command (Unix) |
| `--help` | print usage |

Set `AM_ASSUME_YES=1` in the environment for unattended/CI runs.

---

## The launcher (`launch.sh` / `launch.ps1`)

1. Verifies the environment is intact (`.venv`, `node_modules`, `.next` build)
   and that ports 8000/3000 are free.
2. Boots the **FastAPI backend** (`:8000`) and **Next.js frontend** (`:3000`)
   concurrently in the background.
3. Polls `http://localhost:8000/api/health` until both answer.
4. Opens your default browser to the portal and prints the LAN address so
   colleagues on the same network can reach it.
5. Traps **Ctrl-C** (SIGINT) / SIGTERM and stops **both** processes — no
   orphaned ports.

| Flag | Effect |
|---|---|
| `--no-browser` | start without opening a browser |
| `--service` | foreground, no browser (for systemd / headless) |

Override ports with `BACKEND_PORT` / `FRONTEND_PORT`, and the bind address with
`HOST_BIND` (default `0.0.0.0`, i.e. reachable on the LAN — set to `127.0.0.1`
to keep it local-only).

---

## Offline / air-gapped deployment

For sites with no internet, build a portable bundle on a connected machine and
load it on the target:

```bash
# On a connected machine:
./deploy/package_offline.sh          # → antennamaster-offline.tar (images + assets)

# On the air-gapped host:
./deploy/load_offline.sh antennamaster-offline.tar
docker compose up -d                 # or ./launch.sh after ./install.sh --no-sudo
```

The DEM tiles the app has already cached travel with the bundle, and the local
base-map tile server (`/api/basemap`) plus PWA service worker keep the map
rendering with no network. See `DEPLOYMENT_GUIDE.md` for the full matrix
(Docker, native, systemd) and firewall notes.

---

## Run as a service (Linux, systemd)

```bash
sudo cp -r . /opt/antennamaster
sudo /opt/antennamaster/install.sh --yes
sudo cp deploy/rf-simulator.service /etc/systemd/system/
sudo systemctl enable --now rf-simulator
```

The unit runs `launch.sh --service` (foreground, no browser) and restarts on
failure.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Python 3.10+ is required and could not be installed automatically" | Install Python 3.11 from python.org (or your manager), re-open the shell, re-run the installer. |
| "Node.js 18+ is required…" | Install the Node LTS from nodejs.org (or `winget install OpenJS.NodeJS.LTS`), re-run. |
| A dependency fails to build (`pyproj`, `scipy`) | The installer resolves the compiler toolchain and retries; if it still fails, install `build-essential` (Linux) / Xcode CLT (macOS) / MSVC Build Tools (Windows) and re-run. |
| "Port 8000/3000 is already in use" | Another instance is running — stop it, or set `BACKEND_PORT` / `FRONTEND_PORT`. |
| Windows: "running scripts is disabled on this system" | Launch with `powershell -ExecutionPolicy Bypass -File .\install.ps1`. |
| The browser didn't open | Open http://localhost:3000 manually — the servers are still running. |

Re-running `install.*` is always safe: completed steps are detected and skipped.
