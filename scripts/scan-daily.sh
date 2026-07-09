#!/usr/bin/env bash
#
# Trigger a Greenblatt special-situations scan and wait for it to finish.
# Designed to run once a day from cron on the Pi (see install notes at bottom).
#
# It POSTs to the app's scan endpoint, then polls until the run completes and
# logs the result (filings seen / events created, or the error). Exits non-zero
# on failure so cron can surface a problem.
#
# Config via environment (all optional):
#   BASE_URL        default http://localhost:8000
#   LOOKBACK_DAYS   default 7   (how many days of EDGAR filings to (re)scan)
#   LOG_FILE        default $HOME/special-situations/scan.log
#   POLL_TIMEOUT    default 1800 seconds (max wait for the scan to finish)
#   POLL_INTERVAL   default 15 seconds

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
LOG_FILE="${LOG_FILE:-$HOME/special-situations/scan.log}"
POLL_TIMEOUT="${POLL_TIMEOUT:-1800}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"

mkdir -p "$(dirname "$LOG_FILE")"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

# Pull a top-level field out of a JSON blob on stdin, without needing jq.
json_field() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))"; }

log "scan: starting (lookback ${LOOKBACK_DAYS}d) -> ${BASE_URL}"

resp="$(curl -fsS -X POST "${BASE_URL}/api/scan?lookback_days=${LOOKBACK_DAYS}")" || {
  log "scan: ERROR could not reach ${BASE_URL}/api/scan — is the app running?"
  exit 1
}

run_id="$(printf '%s' "$resp" | json_field scan_run_id)"
if [ -z "$run_id" ]; then
  log "scan: ERROR unexpected response: ${resp}"
  exit 1
fi
log "scan: started run #${run_id}"

elapsed=0
while [ "$elapsed" -lt "$POLL_TIMEOUT" ]; do
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))

  status="$(curl -fsS "${BASE_URL}/api/scan/${run_id}")" || { log "scan: status check failed, retrying"; continue; }
  [ "$(printf '%s' "$status" | json_field finished)" = "True" ] || continue

  if [ "$(printf '%s' "$status" | json_field ok)" = "True" ]; then
    seen="$(printf '%s' "$status" | json_field filings_seen)"
    created="$(printf '%s' "$status" | json_field events_created)"
    log "scan: done run #${run_id} — ${seen} filing(s) seen, ${created} event(s) created"
    exit 0
  fi

  log "scan: FAILED run #${run_id} — $(printf '%s' "$status" | json_field error)"
  exit 1
done

log "scan: TIMEOUT after ${POLL_TIMEOUT}s waiting for run #${run_id}"
exit 1

# --- Install on the Pi ------------------------------------------------------
#
#   scp scripts/scan-daily.sh raspberry@garden-pi.local:~/special-situations/scripts/
#   ssh raspberry@garden-pi.local
#   chmod +x ~/special-situations/scripts/scan-daily.sh
#
#   # test it once by hand:
#   ~/special-situations/scripts/scan-daily.sh
#
#   # schedule it for 11:45pm local time, every day:
#   crontab -e
#   # add this line (cron uses the Pi's local timezone):
#   45 23 * * * /home/raspberry/special-situations/scripts/scan-daily.sh
#
# Check `~/special-situations/scan.log` for results. If you use this cron job,
# you can ignore the app's built-in nightly scan (it runs in UTC); running both
# just double-scans (harmless — existing filings are skipped).
