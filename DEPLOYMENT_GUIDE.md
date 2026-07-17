# AntennaMaster — Deployment Guide

Everything an IT team needs to run the RF Coverage Simulator, three ways:

| Method | Best for | Section |
|---|---|---|
| **Docker Compose** | servers, reproducible installs, air-gapped sites | [1](#1-docker-deployment) |
| **Local installer** | a laptop/desktop, a quick trial, a single workstation | [2](#2-local-installer) |
| **systemd service** | a persistent Linux production server (bare-metal) | [3](#3-persistent-service-systemd) |

The platform is two services — a **FastAPI backend** (port 8000) and a
**Next.js frontend** (port 3000). The browser only ever talks to the frontend,
which proxies `/api/*` to the backend. Persistent data (the SQLite database
for accounts/projects/audit, the DEM tile cache, uploaded DXFs and rendered
results) lives in one directory/volume — **there is no separate database
server to run**.

---

## 1. Docker deployment

### Prerequisites
- Docker Engine 24+ and the Compose plugin (`docker compose version`).

### Start
```bash
docker compose up -d --build
```
- Frontend: **http://localhost:3010**
- Backend API docs: http://localhost:8010/docs (published to localhost only)

The frontend waits for the backend's health check before starting; both
restart automatically on failure or host reboot (`restart: unless-stopped`).

### Manage
```bash
docker compose ps           # status + health
docker compose logs -f      # follow logs
docker compose down         # stop (data is preserved in the am_data volume)
docker compose down -v      # stop and DELETE all data
```

### Data & backups
All state is on the named volume **`am_data`** (mounted at `/data` in the
backend). Back it up with:
```bash
docker run --rm -v antennamaster_am_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/am_data-backup.tgz -C /data .
```

### Configuration
Override any setting in `docker-compose.yml` under the backend's
`environment:` (full list in `backend/app/config.py`). Common ones:

| Variable | Default | Purpose |
|---|---|---|
| `AM_DEM_CACHE_MB` | 2048 | disk budget for the elevation tile cache |
| `AM_CORS_ORIGINS` | `*` | lock to your domain(s) in production |
| `AM_SAAS_MODE` | unset | `1` enforces accounts/tiers/quotas |
| `AM_DSM_URL` | unset | optional building/canopy surface-model tiles |
| `UVICORN_WORKERS` | 2 | backend worker processes |

**Splitting frontend and backend across hosts:** the frontend bakes the API
proxy target at build time, so rebuild it pointing at the backend host:
```bash
docker build --build-arg BACKEND_URL=http://10.0.0.5:8000 \
  -t antennamaster-frontend:latest ./frontend
```

### Offline / air-gapped deployment
For remote or secure industrial sites with **no registry/internet access**:

**On a machine with Docker + internet:**
```bash
./deploy/package_offline.sh          # builds images, writes antennamaster-offline.tar
```
Copy these three files to the target host (USB, secure transfer):
`antennamaster-offline.tar`, `docker-compose.yml`, `deploy/load_offline.sh`.

**On the air-gapped target (Docker installed, no internet):**
```bash
./deploy/load_offline.sh antennamaster-offline.tar
```
This loads the images and starts the stack — no image pulls, no package
downloads. Note: outdoor terrain uses on-demand SRTM tiles from the internet;
in a fully offline site, pre-warm the DEM cache on a connected machine and
copy the `am_data` volume, or point `AM_DEM_URL` at an internal tile mirror.

---

## 2. Local installer

For a single workstation (Linux, macOS or Windows). No Docker required.

### Prerequisites
- **Python 3.10+** and **Node.js 18+** (LTS) on `PATH`.

### Install & run

**Linux / macOS:**
```bash
./install.sh            # scans host, auto-installs missing runtimes, builds
./launch.sh             # starts both servers, waits for health, opens the browser
```

**Windows:**
```bat
install.bat
launch_simulator.bat
```

`install.sh`/`install.bat` check prerequisites, create a dedicated Python
virtualenv, install backend and frontend dependencies, and build the
frontend — with clear, colour-coded success/failure output. They are safe to
re-run.

`launch_simulator.*` boots the FastAPI and Next.js servers, waits until both
answer their health checks, prints the local **and LAN** URLs, and opens your
default browser. Stop with Ctrl-C (Linux/macOS) or by closing the two server
windows (Windows). Flags: `--no-browser` (don't open a browser),
`--service` (foreground, no browser — used by systemd).

---

## 3. Persistent service (systemd)

To run the bare-metal install as an auto-restarting background service on a
Linux production server:

```bash
# 1. Deploy the project (example path) and install it:
sudo mkdir -p /opt/antennamaster && sudo cp -r . /opt/antennamaster
cd /opt/antennamaster && ./install.sh

# 2. Create a dedicated service account and hand it ownership:
sudo useradd -r -s /usr/sbin/nologin antenna
sudo chown -R antenna:antenna /opt/antennamaster

# 3. Install and enable the service:
sudo cp deploy/rf-simulator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rf-simulator

# 4. Verify:
systemctl status rf-simulator
journalctl -u rf-simulator -f
```

The unit starts on boot, restarts on failure, and binds to `0.0.0.0` so the
app is reachable on the LAN. Edit paths, ports or `AM_*` environment in
`deploy/rf-simulator.service` to suit your host.

---

## 4. Network, ports & firewall (LAN access)

| Port | Service | Who needs it |
|---|---|---|
| **3000** | Frontend (the app) | every user's browser |
| 8000 | Backend API + `/docs` | usually **internal only** — the frontend proxies it |

For colleagues on the same network to reach the tool, open **TCP 3000** to
the LAN and share `http://<server-ip>:3000`.

**Linux (ufw):**
```bash
sudo ufw allow from 192.168.0.0/16 to any port 3000 proto tcp
```
**Linux (firewalld):**
```bash
sudo firewall-cmd --permanent --add-port=3000/tcp && sudo firewall-cmd --reload
```
**Windows:**
```powershell
New-NetFirewallRule -DisplayName "AntennaMaster" -Direction Inbound `
  -LocalPort 3000 -Protocol TCP -Action Allow
```

### Production hardening (recommended)
- **Don't expose port 8000** to the LAN — in `docker-compose.yml` it is bound
  to `127.0.0.1` by default; keep it that way (or remove the mapping entirely).
- **Front the app with a reverse proxy** (nginx/Caddy/Traefik) terminating
  **HTTPS** and forwarding to `frontend:3000`. Geolocation ("Use my GPS")
  and the offline PWA require a secure context (HTTPS or localhost).
- Set **`AM_CORS_ORIGINS`** to your exact domain instead of `*`.
- For multi-tenant use, set **`AM_SAAS_MODE=1`** (enforces accounts, tiers and
  quotas) and configure a billing secret — see `SaaS_ARCHITECTURE.md`.

---

## 5. Health, verification & troubleshooting

**Health endpoints:**
- `GET /api/health` — liveness (process up).
- `GET /api/ready` — readiness (data dir writable, DEM cache state, DSM
  configured).

**Quick smoke test after deploy:**
```bash
curl -s http://localhost:8010/api/health                 # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3010/   # 200
curl -s http://localhost:3010/api/rf/technologies | head -c 80    # proxied JSON
```

| Symptom | Cause & fix |
|---|---|
| Frontend loads but every study errors | Backend down or wrong proxy target — check `docker compose ps` / `journalctl`; for split hosts rebuild the frontend with the right `BACKEND_URL`. |
| "Use my GPS" does nothing | Browser geolocation needs HTTPS (or localhost) — put the app behind an HTTPS reverse proxy. |
| Coverage/terrain returns 502 | The backend can't reach the SRTM tile source — check outbound internet or set `AM_DEM_URL` to an internal mirror. |
| Port already in use | Another process holds 3000/8000 — stop it or change `FRONTEND_PORT`/`BACKEND_PORT` (bare-metal) or the `ports:` mapping (Docker). |
| Out of disk over time | The DEM tile cache grows to `AM_DEM_CACHE_MB` (default 2 GB) and self-evicts; lower it if needed. |

**Validate the whole build before shipping:**
```bash
./start.sh --check        # backend tests + benchmark gates + frontend tests
```
