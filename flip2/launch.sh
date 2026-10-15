#!/bin/sh
# Underground Rap Machine on the Retroid Pocket Flip 2 (ROCKNIX).
# Starts the bridge (server.py: serves the page on 127.0.0.1:8766 and drives the stick LED rings),
# opens the page in the house Firefox (kiosk) through its launcher, and once Firefox is up swaps in
# the controller profile for the rap machine. Leave with Guide (Home) or the L1+Select+Start chord;
# everything is cleaned up and the rings go back to what they showed.
#   URM_PORT=8766   URM_REMOTE=1 adds ?remote so `server.py --key ...` can drive the page over ssh

[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1
APP=/storage/apps/rap-machine
FF=/storage/apps/firefox-rocknix
PORT=${URM_PORT:-8766}
LOG=$APP/logs/launch.log
mkdir -p "$APP/logs"
echo "===== $(date -u +%FT%TZ) launch" >> "$LOG"

[ -x "$FF/launch.sh" ] || { echo "house Firefox launcher not found at $FF/launch.sh" | tee -a "$LOG" >&2; exit 1; }

SRV=""; FFL=""
cleanup() {
  trap - EXIT INT TERM HUP
  [ -n "$FFL" ] && kill "$FFL" 2>/dev/null
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null
  [ -n "$SRV" ] && wait "$SRV" 2>/dev/null
  echo "$(date -u +%FT%TZ) exit" >> "$LOG"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

python3 "$APP/server.py" --port "$PORT" --dir "$APP" >> "$APP/logs/server.log" 2>&1 &
SRV=$!
i=0
while [ $i -lt 20 ]; do
  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/status', timeout=1)" 2>/dev/null && break
  i=$((i + 1)); sleep 0.25
done

touch "$APP/.started"
URL="http://127.0.0.1:$PORT/underground-rap-machine.html?flip${URM_REMOTE:+&remote}"
"$FF/launch.sh" --kiosk "$URL" &
FFL=$!

# The house launcher loads its own InputPlumber profile before it starts Firefox and writes the pid
# file after; ours goes in once that file is newer than this launch.
i=0
while [ $i -lt 60 ] && kill -0 "$FFL" 2>/dev/null; do
  if [ "$FF/firefox.pid" -nt "$APP/.started" ]; then
    if busctl call org.shadowblip.InputPlumber /org/shadowblip/InputPlumber/CompositeDevice0 \
         org.shadowblip.Input.CompositeDevice LoadProfilePath s "$APP/rap-machine.yaml" >> "$LOG" 2>&1; then
      echo "controller profile loaded" >> "$LOG"
    else
      echo "controller profile NOT loaded (busctl failed)" >> "$LOG"
    fi
    break
  fi
  i=$((i + 1)); sleep 0.5
done

wait "$FFL"
