# Deploying to a Raspberry Pi (native, no Docker)

The app is now a **single FastAPI process**: it serves the JSON API, the
server-rendered UI (Jinja2 + HTMX), and runs the nightly scan in-process, backed
by one SQLite file. No Docker, no Node, no build step — ideal for an always-on
Raspberry Pi 3B (1 GB).

You run **one command** (`uvicorn app.main:app`) on **one port** (8000), kept
alive by systemd. That's the whole deployment.

---

## 1. Prereqs on the Pi (once)

64-bit Raspberry Pi OS recommended. Install Python + a couple of build headers
(in case `lxml` needs to compile):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git libxml2-dev libxslt1-dev

# Optional but recommended on 1 GB: a little compressed swap.
sudo apt install -y zram-tools
echo -e "ALGO=zstd\nPERCENT=150" | sudo tee /etc/default/zramswap
sudo systemctl restart zramswap
```

---

## 2. Get the code + install

```bash
cd ~
git clone https://github.com/djlisbonne/special-situations.git
cd special-situations
git checkout outcome-tracking-and-parsing-fix

python3 -m venv .venv
source .venv/bin/activate
pip install -e ./backend          # installs FastAPI, uvicorn, jinja2, etc.
mkdir -p data                     # holds the SQLite file
```

---

## 3. Configure

The app reads its `.env` from the backend working directory:

```bash
cp .env.example backend/.env
nano backend/.env
```

Set these (copy the API keys from wherever you had them):

```
OPENAI_API_KEY=sk-...
POLYGON_API_KEY=...
SEC_EDGAR_USER_AGENT="Your Name your.email@example.com"
DATABASE_URL=sqlite:////home/raspberry/special-situations/data/greenblatt.db
```

> Use the **absolute** SQLite path (four slashes after `sqlite:`), and leave
> `NEXT_PUBLIC_API_BASE` unset — there's no separate frontend anymore, the UI is
> served same-origin.

---

## 4. Run it (quick check)

```bash
cd backend
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **`http://garden-pi.local:8000`** from any device on your network (or the
Pi's IP). The schema is created automatically on first start. `Ctrl-C` to stop,
then set up the service below for always-on.

---

## 5. Always-on with systemd

Create `/etc/systemd/system/greenblatt.service` (adjust the username/paths):

```ini
[Unit]
Description=Greenblatt special-situations app
After=network-online.target
Wants=network-online.target

[Service]
User=raspberry
WorkingDirectory=/home/raspberry/special-situations/backend
ExecStart=/home/raspberry/special-situations/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# Keep memory in check on a 1 GB box (systemd will restart if it's exceeded).
MemoryMax=500M

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now greenblatt
systemctl status greenblatt
journalctl -u greenblatt -f        # live logs
```

It now starts on boot and restarts on crash. Kick off the first scan (the
nightly job then runs on its own):

```bash
curl -XPOST 'http://localhost:8000/api/scan?lookback_days=60'
```

---

## Operating notes

- **One process, one file.** Steady-state ~150–200 MB. The memory spike to watch
  is a scan parsing a 3–4 MB EDGAR information statement (+150–300 MB transiently)
  — keep zram swap on; it pages rather than failing. Don't truncate filing HTML
  to save RAM, that silently drops the financials the tool reads.
- **Updating:** `git pull && .venv/bin/pip install -e ./backend && sudo systemctl restart greenblatt`.
- **Backup:** the database is one file — `cp data/greenblatt.db data/greenblatt.backup.db`.
- **Endpoints:** UI at `/`, JSON API under `/api/...` (e.g. `/api/events`,
  `/api/performance/track-record`).
- **Remote access later:** add [Tailscale](https://tailscale.com) to reach it
  off your home network without exposing ports.

---

## Docker alternative

If you'd rather containerize, `docker-compose.prod.yml` now runs the same single
service (SQLite, restart policy, memory cap):

```bash
cp .env.example .env        # set keys; DATABASE_URL is overridden to SQLite
docker compose -f docker-compose.prod.yml up -d --build
```

Same single port (8000), same UI + API.
