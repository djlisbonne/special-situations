# Deploying to a Raspberry Pi (always-on)

This runs the whole app on a Pi so your laptop doesn't have to. It targets a
**Raspberry Pi 3B (1 GB RAM)** — the tightest realistic target — using the
production stack in [`docker-compose.prod.yml`](docker-compose.prod.yml).

> **Reality check.** A Pi 3B *can* run this, but 1 GB is the binding constraint.
> The production stack is tuned for it (SQLite instead of Postgres, Next.js
> standalone runtime, memory caps), and you **build the images on your laptop**
> because `next build` will not fit in 1 GB. If you have (or can get) a **Pi 4/5
> with 4 GB+**, everything below still works and you can optionally build on the
> Pi directly — it'll just be much more comfortable. Note the LLM/market work
> happens via external APIs, so CPU on the Pi is rarely the bottleneck; RAM is.

The architecture decision: **yes, use Docker.** It's not too heavy for a Pi —
the daemon idles at tens of MB, and the app is already containerized so your Pi
and laptop stay identical. Hand-rolling systemd services would just cost you
reproducibility.

---

## 1. Prepare the Pi (once)

1. **Flash 64-bit Raspberry Pi OS Lite** (no desktop — save the RAM). The 64-bit
   OS is required so the `arm64` images run.
2. SSH in, update, and install Docker:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out/in afterwards
   ```
3. **Add compressed swap (zram).** Cheap insurance against memory spikes, and
   far kinder to the SD card than a swapfile:
   ```bash
   sudo apt install -y zram-tools
   echo -e "ALGO=zstd\nPERCENT=200" | sudo tee /etc/default/zramswap
   sudo systemctl restart zramswap
   ```

Docker's service is enabled on boot by default, and our `restart: unless-stopped`
policy brings the containers back after any reboot or power blip — that's what
makes it "always on."

---

## 2. Build the images on your laptop

The Pi can't build them. On your Mac (Docker Desktop has `buildx` with arm64
emulation), from the repo root. Replace `<PI>` with the Pi's hostname or IP
(e.g. `raspberrypi.local` or `192.168.1.50`):

```bash
PI=raspberrypi.local

docker buildx build --platform linux/arm64 \
  -t greenblatt-backend:prod --load ./backend

docker buildx build --platform linux/arm64 \
  -f frontend/Dockerfile.prod \
  --build-arg NEXT_PUBLIC_API_BASE=http://$PI:8000 \
  -t greenblatt-frontend:prod --load ./frontend
```

> **The single most important flag** is `--build-arg NEXT_PUBLIC_API_BASE=http://$PI:8000`.
> That value is compiled into the browser bundle, so it must be the address your
> *laptop/phone browser* uses to reach the Pi. If you leave it as `localhost`,
> the dashboard will load but show no data.

---

## 3. Ship the images to the Pi

No registry needed — stream them over SSH:

```bash
docker save greenblatt-backend:prod greenblatt-frontend:prod \
  | gzip | ssh $PI 'gunzip | docker load'
```

(Each image is a few hundred MB; over Wi-Fi this takes a few minutes.)

---

## 4. Get the repo + secrets onto the Pi

You still need the compose file and your `.env` on the Pi:

```bash
ssh $PI
git clone https://github.com/djlisbonne/special-situations.git
cd special-situations
cp .env.example .env
nano .env     # fill in OPENAI_API_KEY, POLYGON_API_KEY, SEC_EDGAR_USER_AGENT
              # set NEXT_PUBLIC_API_BASE=http://<PI>:8000
```

`.env` is gitignored, so it never leaves the Pi.

---

## 5. Run it

```bash
docker compose -f docker-compose.prod.yml up -d
```

This uses the images you loaded (it won't rebuild). The backend creates the
SQLite schema automatically on first start. Check it:

```bash
docker compose -f docker-compose.prod.yml ps
curl -fsS http://localhost:8000/health        # {"ok": true}
docker stats --no-stream                      # watch memory headroom
```

From any device on your network, open **`http://<PI>:3000`**.

Kick off the first scan (the nightly job then runs on its own):

```bash
curl -XPOST 'http://localhost:8000/scan?lookback_days=60'
```

---

## Operating notes

- **Updating:** rebuild on the laptop (step 2), re-ship (step 3), then on the Pi
  `docker compose -f docker-compose.prod.yml up -d`. SQLite data persists in the
  `appdata` volume.
- **Backups:** the database is a single file. Snapshot it with
  `docker run --rm -v special-situations_appdata:/d -v $PWD:/b alpine cp /d/greenblatt.db /b/`.
- **Memory (1 GB Pi, shared with another app):** steady state is ~300-370 MB for
  the three containers; the spike to watch is a **scan**, when parsing a 3-4 MB
  EDGAR information statement transiently adds 150-300 MB. Keep swap on (zram) —
  that spike is meant to page, not OOM-kill, and scans run at night. Levers if
  it's still tight: lower `SCAN_LOOKBACK_DAYS` (fewer filings per run), trigger
  scans manually when your other app is idle, or move to a Pi 4/5.
  Do **not** try to shrink the spike by truncating filing HTML before parsing —
  the financials sit deep in the document, so that just silently drops the data
  the tool exists to read.
- **Why SQLite here:** the app uses no Postgres-specific features, and on 1 GB a
  second database process is a luxury. To use Postgres instead, add a `db`
  service and set `DATABASE_URL` back to the `postgresql+psycopg://…` form.
- **Remote access (later):** for reaching it off your home network, add
  [Tailscale](https://tailscale.com) on the Pi and your devices — no port
  forwarding, no exposing anything to the internet.
