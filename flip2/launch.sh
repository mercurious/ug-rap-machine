#!/bin/sh
# Underground Rap Machine on the Retroid Pocket Flip 2 (ROCKNIX).
# Starts the bridge (server.py: serves the page on 127.0.0.1:8766 and drives the stick LED rings),
# then opens the page in Donkey (https://github.com/mercurious/donkey) in kiosk mode, on its own profile
# (donkey-rap-machine) with the rap machine's controller profile and prefs. Leave with Guide (Home) or the
# L1+Select+Start chord; Donkey restores the controller, and the rings go back to what they showed.
#   DONKEY_HOME=...  where Donkey lives (default: from the Donkey port entry, else /storage/apps/donkey)
#   URM_PORT=8766   URM_REMOTE=1 adds ?remote so `server.py --key ...` can drive the page over ssh
#   URM_AI=1 also starts Gemma (llama-server, E4B with its MTP head, big cores) and Pocket TTS
#   (tts-server) from the retro-voice-chat llamatalk kit for the MC mode; URM_MODEL=e2b for the small
#   model. URM_LLM_PORT=8096 URM_TTS_PORT=8097 URM_VOICE=alba
#   URM_LINK_PORT=47800 the jam-link beacon on the LAN (tempo, key, chords for autojam; 0 = off)
#   URM_SYNC=auto URM_SYNC_PORT=5150 Wi-Fi sync with HI5, Jaffedrone and fliptribe (HI5S; off|auto|lead|follow, port 0 = off)

[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1
APP=/storage/apps/rap-machine
PORT=${URM_PORT:-8766}
LOG=$APP/logs/launch.log
mkdir -p "$APP/logs"
echo "===== $(date -u +%FT%TZ) launch" >> "$LOG"

# Donkey's home: $DONKEY_HOME, else the launcher its port entry runs, else the default install.
DONKEY=${DONKEY_HOME:-}
if [ -z "$DONKEY" ] && [ -f /storage/roms/ports/Donkey.sh ]; then
  DONKEY=$(sed -n 's|.*"\(/[^"]*\)/launch\.sh".*|\1|p' /storage/roms/ports/Donkey.sh | head -n 1)
fi
DONKEY=${DONKEY:-/storage/apps/donkey}
[ -x "$DONKEY/launch.sh" ] || { echo "Donkey not found at $DONKEY/launch.sh (https://github.com/mercurious/donkey)" | tee -a "$LOG" >&2; exit 1; }
# One Donkey session at a time; Donkey refuses a second one too, but say why before starting anything.
if FP=$(cat /run/donkey/firefox.pid 2>/dev/null) && [ -n "$FP" ] && kill -0 "$FP" 2>/dev/null; then
  echo "Donkey is already running (pid $FP); leave it first (Home, or L1+Select+Start)" | tee -a "$LOG" >&2; exit 1
fi
if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/status', timeout=1)" 2>/dev/null; then
  echo "something already answers on port $PORT; is the rap machine running?" | tee -a "$LOG" >&2; exit 1
fi

SRV=""; FFL=""; AIPIDS=""; BOOST=""
cleanup() {
  trap - EXIT INT TERM HUP
  [ -n "$BOOST" ] && kill "$BOOST" 2>/dev/null
  [ -n "$FFL" ] && kill "$FFL" 2>/dev/null
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null
  [ -n "$SRV" ] && wait "$SRV" 2>/dev/null
  for p in $AIPIDS; do kill "$p" 2>/dev/null; done
  for p in $AIPIDS; do while kill -0 "$p" 2>/dev/null; do sleep 0.2; done; done
  echo "$(date -u +%FT%TZ) exit" >> "$LOG"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

# MC mode: the language model and the voice, from the llamatalk kit that Retro Voice Chat installs.
# SM8250: 0-3 little, 4-6 big, 7 prime. The model and the voice run on 4-6 only, at low priority and
# (the model) as a batch task, so the beat never waits for them: Firefox's audio graph, which also runs
# the auto-tune worklet, keeps the prime core and gets a real-time slice (see audio_boost below).
# Different ports from Retro Voice Chat so both can be installed.
AI_ARGS=""
if [ -n "${URM_AI:-}" ]; then
  LT=${URM_LLAMATALK:-/storage/games-external/retro-voice-chat/llamatalk}
  M=${URM_MODELS:-$("$LT/models.sh" path 2>/dev/null)}; M=${M:-/storage/games-external/models}
  LLM_PORT=${URM_LLM_PORT:-8096}; TTS_PORT=${URM_TTS_PORT:-8097}
  if [ "${URM_MODEL:-e4b}" = e2b ]; then
    LLM_MODEL=gemma-4-E2B_q4_0-it; DRAFT=""; OMPENV="env -u OMP_PROC_BIND -u OMP_PLACES"; TB=3
  else
    LLM_MODEL=gemma-4-E4B_q4_0-it; DRAFT="-md $M/mtp-gemma-4-E4B-it-Q4_0.gguf --spec-type draft-mtp"
    OMPENV="env OMP_PROC_BIND=close OMP_PLACES={4},{5},{6}"; TB=3
  fi
  missing=""
  for f in "$LT/bin/llama-server" "$LT/bin/tts-server" "$M/$LLM_MODEL.gguf" "$M/pocket-tts-english_2026-09-Q8_0.gguf" "$M/pocket-tts-english_2026-09-voices.gguf"; do
    [ -e "$f" ] || missing="$missing $f"
  done
  if [ -n "$missing" ]; then
    echo "MC mode needs the llamatalk kit and models (install Retro Voice Chat); missing:$missing" | tee -a "$LOG" >&2
  else
    [ -f "$M/mtp-gemma-4-E4B-it-Q4_0.gguf" ] || DRAFT=""
    ulimit -c 0
    env GGML_BACKEND=CPU PT_THREADS=2 nice -n 5 taskset -c 4-6 "$LT/bin/tts-server" \
      --model "$M/pocket-tts-english_2026-09-Q8_0.gguf" --voices "$M/pocket-tts-english_2026-09-voices.gguf" \
      --voice "${URM_VOICE:-alba}" --host 127.0.0.1 --port "$TTS_PORT" >> "$APP/logs/tts.log" 2>&1 &
    AIPIDS="$AIPIDS $!"
    $OMPENV nice -n 10 chrt -b 0 taskset -c 4-6 "$LT/bin/llama-server" -m "$M/$LLM_MODEL.gguf" $DRAFT -dev none -t 2 -tb $TB -fa on \
      -c 8192 -np 1 --jinja -rea off --cache-ram 0 --host 127.0.0.1 --port "$LLM_PORT" >> "$APP/logs/llm.log" 2>&1 &
    AIPIDS="$AIPIDS $!"
    AI_ARGS="--llm http://127.0.0.1:$LLM_PORT --tts http://127.0.0.1:$TTS_PORT --voice ${URM_VOICE:-alba}"
    echo "MC mode: $LLM_MODEL on :$LLM_PORT, Pocket TTS on :$TTS_PORT" >> "$LOG"
  fi
fi

python3 "$APP/server.py" --port "$PORT" --dir "$APP" $AI_ARGS >> "$APP/logs/server.log" 2>&1 &
SRV=$!
i=0
while [ $i -lt 20 ]; do
  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/status', timeout=1)" 2>/dev/null && break
  i=$((i + 1)); sleep 0.25
done

URL="http://127.0.0.1:$PORT/underground-rap-machine.html?flip${URM_REMOTE:+&remote}${AI_ARGS:+&mc}"
DONKEY_PROFILE=rap-machine DONKEY_CONTROLLER="$APP/rap-machine.yaml" DONKEY_PREFS="$APP/rap-machine.prefs" \
  "$DONKEY/launch.sh" --kiosk "$URL" &
FFL=$!

# Firefox's audio graph threads (the beat, the vocal chain and the auto-tune worklet all render there)
# get a real-time round-robin slice and the big cores, so the model's threads never make them wait
# or push them onto the little cores. New graph threads appear whenever audio starts, so keep looking.
audio_boost() {
  while :; do
    for p in $(pidof firefox-bin); do
      for t in /proc/"$p"/task/*; do
        case "$(cat "$t/comm" 2>/dev/null)" in
          MediaTrackGrph|GraphRunner|AudioIP*allback|cubeb*|NativeAudio*)
            [ "$(awk '{print $41}' "$t/stat" 2>/dev/null)" = 2 ] && continue
            chrt -r -p 5 "${t##*/}" 2>/dev/null && taskset -p -c 4-7 "${t##*/}" >/dev/null 2>&1 ;;
        esac
      done
    done
    sleep 3
  done
}
audio_boost &
BOOST=$!

wait "$FFL"
