#!/usr/bin/env python3
"""Underground Rap Machine bridge for the Retroid Pocket Flip 2 (ROCKNIX).

Serves the app on http://127.0.0.1:PORT (a secure context, so Firefox allows the mic) and drives
the RGB rings around the sticks from the page. Standard library only (ROCKNIX ships python3).

  POST /led     {"l": [[r,g,b] ×4], "r": [[r,g,b] ×4]}  segment colours 0–255, clockwise from the top
  POST /status  any JSON: the page's heartbeat (sent when opened with ?remote); GET /status returns it
  POST /cmd     {"key": "m"} | {"click": "#gen"} | {"set": ["#bpm", 120]}: queued for the page,
                which long-polls GET /cmd?wait=20 when opened with ?remote. Lets ssh drive the page.

  server.py --port 8766 --dir /storage/apps/rap-machine     serve (the launcher does this)
  server.py --test                                           light each segment in turn, to check ORDER
  server.py --key m | --click "#gen" | --set "#bpm" 120      send a command to the running server
  server.py --status                                         print the page's last heartbeat
  server.py --grant-mic                                      allow the mic for this origin in the house
                                                             Firefox profile (Firefox must be closed)
  server.py --llm http://127.0.0.1:8096 --tts http://127.0.0.1:8097
                                                             also bridge Gemma (llama-server) and Pocket TTS
                                                             (tts-server) for the MC mode: POST /ai/plan starts the
                                                             model writing a performance (JSON) and returns a job
                                                             number, GET /ai/progress follows it, GET /ai/plan?job=N
                                                             fetches the result; POST /ai/tts sings a line; GET
                                                             /ai/health reports the servers;
  server.py --llm http://HOST:11434/v1 --llm-model gemma4:e4b
                                                             any other OpenAI-compatible server (Ollama, a shared
                                                             GPU box): name the model it should run. A base URL
                                                             ending in /v1 is taken either way
  GET /sys                                                   battery, the default audio output and model activity
                                                             for the page gauges. USB headphones become the default
                                                             output while plugged in (see Headphones)
  POST /link    the page, once a bar: tempo, key, mode, the chord loop, which bar and when its downbeat is heard;
                GET /link returns it. The bridge beacons it on the LAN (UDP broadcast, --link-port, default
                47800, 0 = off) four times a second, with the next downbeat as "nextBarIn" milliseconds from the
                send, so a jam partner (autojam) follows exactly without the two clocks having to agree.
  GET /sync, POST /sync {"mode": "off|auto|lead|follow"}
                Wi-Fi sync with HI5, Jaffedrone and fliptribe: the "HI5S" packet on UDP 5150 (--sync-port), 32
                bytes ten times a second with tempo, transport and the 16th-step position. The lowest id, or a
                unit set to LEAD, leads; the others follow. The bridge sends for the page from its bar reports,
                and GET /sync hands the page the leader it should follow (tempo, playing, position now).

The rings are restored to what they showed before when the server exits.
"""
import argparse, json, math, os, random, re, signal, socket, sqlite3, struct, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

LED_ROOT = "/sys/class/leds"
# Which sysfs segment (rgb:l1..4 / rgb:r1..4) sits where on each ring, clockwise from the top.
# The segments are numbered counter-clockwise on the Flip 2, so the clock runs 1, 4, 3, 2.
# Verify with --test and fix here if it runs the wrong way round.
ORDER = {"l": [1, 4, 3, 2], "r": [1, 4, 3, 2]}
PROFILE = "/storage/.mozilla/firefox-rocknix"


class Ring:
    """One stick's four RGB segments. multi_intensity takes the channels in the order of multi_index
    (blue green red on this kernel), so the order is read, not assumed."""

    def __init__(self, side):
        self.leds, self.saved = [], []
        for n in ORDER[side]:
            d = f"{LED_ROOT}/rgb:{side}{n}"
            with open(f"{d}/multi_index") as f:
                idx = f.read().split()
            with open(f"{d}/multi_intensity") as f:
                mi = f.read().strip()
            with open(f"{d}/brightness") as f:
                br = f.read().strip()
            self.saved.append((d, mi, br))
            self.leds.append((open(f"{d}/multi_intensity", "w"), idx))
            with open(f"{d}/brightness", "w") as f:
                f.write("255\n")

    def set(self, colours):
        for (f, idx), rgb in zip(self.leds, colours):
            ch = {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}
            f.write(" ".join(str(max(0, min(255, int(ch[c])))) for c in idx) + "\n")
            f.flush()

    def restore(self):
        for d, mi, br in self.saved:
            try:
                with open(f"{d}/multi_intensity", "w") as f:
                    f.write(mi + "\n")
                with open(f"{d}/brightness", "w") as f:
                    f.write(br + "\n")
            except OSError:
                pass


class Rings:
    def __init__(self):
        try:
            self.l, self.r = Ring("l"), Ring("r")
            self.ok = True
        except OSError as e:
            print(f"no stick LEDs here ({e}); /led will answer 503", flush=True)
            self.ok = False

    def set(self, frame):
        self.l.set(frame["l"])
        self.r.set(frame["r"])

    def restore(self):
        if self.ok:
            self.l.restore()
            self.r.restore()


class State:
    def __init__(self, ai):
        self.rings = Rings()
        self.ai = ai
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.cmds = []
        self.status = {}
        self.link, self.link_t = None, 0.0   # the page's last bar report and when it came
        self.sync = None                     # the HI5S peer, when it runs
        self.phones = Headphones()


class Headphones:
    """USB headphones take the sound while they are plugged in. Firefox here has no AudioContext.setSinkId, but its
    output follows PipeWire's default sink, so when a USB output arrives the bridge makes it the default, and when it
    leaves (or the bridge exits) puts back the default it replaced. A default someone picks by hand meanwhile is left
    alone. Needs pactl (pipewire-pulse); without it this does nothing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.out = None      # the default output for GET /sys: {"name", "usb"}
        self.ours = None     # the USB sink the bridge made the default
        self.prev = None     # the default it replaced
        self.seen = set()
        self.env = dict(os.environ)
        if not self.env.get("XDG_RUNTIME_DIR"):   # started from ssh: find the session's pulse socket
            for d in (f"/run/user/{os.getuid()}", "/var/run/0-runtime-dir"):
                if os.path.exists(os.path.join(d, "pulse", "native")):
                    self.env["XDG_RUNTIME_DIR"] = d
                    break

    def _pactl(self, *args):
        return subprocess.run(["pactl", *args], env=self.env, capture_output=True, text=True, timeout=5).stdout

    def check(self):
        with self.lock:
            sinks = json.loads(self._pactl("-f", "json", "list", "sinks") or "[]")
            default = self._pactl("get-default-sink").strip()
            names = {s["name"] for s in sinks}
            usb = [s["name"] for s in sinks if (s.get("properties") or {}).get("device.bus") == "usb"]
            new = [n for n in usb if n not in self.seen]
            self.seen = set(usb)
            if self.ours and self.ours in names and default != self.ours:
                self.ours = self.prev = None          # picked another output by hand: not ours any more
            if new and default not in usb:
                self.prev, self.ours = self.prev or default, new[-1]
                self._pactl("set-default-sink", self.ours)
                default = self.ours
                print(f"headphones: {self.ours} plugged in, now the default output (was {self.prev})", flush=True)
            elif self.ours and self.ours not in names:
                if self.prev in names:
                    self._pactl("set-default-sink", self.prev)
                    default = self.prev
                print(f"headphones: {self.ours} unplugged, default output back to {default}", flush=True)
                self.ours = self.prev = None
            desc = next((s.get("description") or s["name"] for s in sinks if s["name"] == default), default)
            self.out = {"name": desc, "usb": default in usb} if default else None

    def run(self):
        while True:
            try:
                self.check()
                p = subprocess.Popen(["pactl", "subscribe"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in p.stdout:
                    if re.search(r"'(new|remove)' on sink #|on server", line):
                        self.check()
                p.wait()
            except FileNotFoundError:
                return                                # no pactl: not a PipeWire box
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                print(f"headphones: {e}", flush=True)
            time.sleep(2)                             # PipeWire restarted: subscribe again

    def restore(self):
        with self.lock:
            try:
                if self.ours and self._pactl("get-default-sink").strip() == self.ours:
                    self._pactl("set-default-sink", self.prev)
                    print(f"headphones: default output back to {self.prev}", flush=True)
            except (OSError, subprocess.SubprocessError):
                pass


def beacon(state, port):
    """The jam link: what the page plays, broadcast on the LAN 4x a second while it reports (read-only)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    host = socket.gethostname()
    while True:
        time.sleep(0.25)
        with state.lock:
            d, t = state.link, state.link_t
        if not d or time.time() - t > 6:      # the page went away: say nothing
            continue
        msg = {k: v for k, v in d.items() if k not in ("barAt", "gbar", "lat")}
        msg.update(app="rap-machine", v=1, host=host)
        bpm, at = d.get("bpm") or 0, d.get("barAt")
        if d.get("playing") and at and bpm > 0:
            now, bar_ms = time.time() * 1000, 240000 / bpm
            k = math.ceil((now - at) / bar_ms)
            msg["nextBarIn"] = round(at + k * bar_ms - now, 1)
            msg["bar"] = (d.get("bar", 0) + k) % max(1, len(d.get("chords") or [0]))
        else:
            msg["playing"] = False
        try:
            s.sendto(json.dumps(msg).encode(), ("255.255.255.255", port))
        except OSError:
            pass                               # no network right now


def link_pos(d, now_ms):
    """The page's position in 16th steps at wall time now_ms, from its last bar report, as rendered (the report
    gives when the downbeat is heard; the output latency is added back so it compares with other engines)."""
    bpm, at = d.get("bpm") or 0, d.get("barAt")
    if not (d.get("playing") and at and bpm > 0):
        return None
    step_ms = 15000 / bpm
    return d.get("gbar", 0) * 16 + (now_ms - at + (d.get("lat") or 0)) / step_ms


class Sync:
    """HI5S v1, the Wi-Fi sync of HI5, Jaffedrone and fliptribe (UDP broadcast, port 5150). Every unit sends
    32 bytes ten times a second: "HI5S", version 1, playing, role (1 AUTO, 2 LEAD, 3 FOLLOW), a reserved byte, a
    random id (u32), the tempo (f32), the position in 16th steps (f64, unwrapped) and its own clock (u64 µs,
    ignored), little-endian. LEAD outranks AUTO, ties go to the lowest id, FOLLOW never leads; a peer is gone
    after 3 s of silence. The bridge speaks for the page: it sends what the page last reported, and the page
    follows the elected leader through GET /sync (the phase loop runs in the page, which owns the clock)."""
    PKT = struct.Struct("<4sBBBxIfdQ")
    ROLES = {"auto": 1, "lead": 2, "follow": 3}
    RANK = {1: 1, 2: 0}   # anything else (FOLLOW) is 3: never leads

    def __init__(self, state, port, mode):
        self.state, self.port, self.mode = state, port, mode if mode in ("off", "auto", "lead", "follow") else "auto"
        self.id = random.SystemRandom().randrange(1, 2 ** 32)
        self.peers = {}      # id -> {role, playing, bpm, pos, t, ip}
        self.bcast, self.bcast_t = [], 0.0
        self.sock = None

    def open(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # HI5's own synctest or another app may share the port
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", self.port))
        s.settimeout(0.02)
        self.sock = s

    def broadcasts(self):
        """Every IPv4 interface's broadcast address (ip -4 -o addr), refreshed every 5 s; 255.255.255.255 if none."""
        if time.time() - self.bcast_t > 5:
            self.bcast_t, out = time.time(), []
            try:
                txt = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=2).stdout
                for line in txt.splitlines():
                    w = line.split()
                    if "brd" in w and " lo " not in f" {w[1]} ":
                        out.append(w[w.index("brd") + 1])
            except (OSError, ValueError, IndexError):
                pass
            self.bcast = out or ["255.255.255.255"]
        return self.bcast

    def elect(self, now):
        """(leader id or None, leading): best rank, then lowest id, over this unit and the peers heard lately."""
        for k in [k for k, p in self.peers.items() if now - p["t"] > 3]:
            del self.peers[k]
        cands = [(self.RANK.get(p["role"], 3), k) for k, p in self.peers.items()]
        me = self.RANK.get(self.ROLES.get(self.mode), 3)
        if me < 3:
            cands.append((me, self.id))
        cands = [c for c in cands if c[0] < 3]
        if not cands:
            return None, False
        best = min(cands)[1]
        return (None, True) if best == self.id else (best, False)

    def run(self):
        last_send = 0.0
        while True:
            try:
                b, addr = self.sock.recvfrom(64)
                if self.mode != "off" and len(b) >= 32:
                    magic, ver, playing, role, pid, bpm, pos, _ = self.PKT.unpack_from(b)
                    if magic == b"HI5S" and ver == 1 and pid != self.id:
                        now = time.time()
                        with self.state.lock:
                            old = self.peers.get(pid)
                            hist = old["hist"] if old and old["bpm"] == bpm and old["playing"] == bool(playing) else []
                            hist = [h for h in hist if now - h[0] < 8] + [(now, pos)]
                            self.peers[pid] = {"role": role, "playing": bool(playing), "bpm": bpm, "pos": pos,
                                               "t": now, "ip": addr[0], "hist": hist}
            except socket.timeout:
                pass
            except OSError:
                time.sleep(0.5)
            now = time.time()
            if self.mode == "off" or now - last_send < 0.1:
                continue
            last_send = now
            with self.state.lock:
                d, t = self.state.link, self.state.link_t
            if not d or now - t > 6:      # no page: say nothing
                continue
            pos = link_pos(d, now * 1000)
            playing = pos is not None
            if pos is None:
                pos = 0.0                  # stopped: a follower that starts with us loads the top of the bar
            pkt = self.PKT.pack(b"HI5S", 1, int(playing), self.ROLES[self.mode], self.id, float(d.get("bpm") or 120),
                                pos, int(time.monotonic() * 1e6))
            for a in self.broadcasts():
                try:
                    self.sock.sendto(pkt, (a, self.port))
                except OSError:
                    pass

    @staticmethod
    def leader_pos(p, now):
        """Where the leader is now. Wi-Fi delivers late, never early, and in power save a broadcast waits for the
        next DTIM beacon, so arrival times scatter by 100 ms and more. Carried on to now at its tempo, the packet
        that puts the leader furthest ahead came through quickest. A leader runs at its stated tempo (only
        followers trim their clocks), so over 8 s the quickest packet pins it to a few ms; a new tempo or a
        start or stop clears the history."""
        v = p["bpm"] / 15
        return max(q + (now - t) * v for t, q in p["hist"])

    def view(self):
        """What the page needs: the mode, who is out there, and the leader to follow with its position now."""
        now = time.time()
        with self.state.lock:
            lid, leading = self.elect(now)
            peers = [{"id": k, "role": {1: "auto", 2: "lead", 3: "follow"}.get(p["role"], "?"), "bpm": round(p["bpm"], 2),
                      "playing": p["playing"], "ip": p["ip"]} for k, p in self.peers.items()]
            out = {"mode": self.mode, "id": self.id, "peers": peers, "leading": leading and bool(peers), "leader": None}
            p = self.peers.get(lid) if lid else None
            if p:
                age = now - p["t"]
                pos = self.leader_pos(p, now) if p["playing"] else p["pos"]
                # "at": when pos holds, on the wall clock the page shares with us (it may read the answer a frame later)
                out["leader"] = {"id": lid, "ip": p["ip"], "bpm": p["bpm"], "playing": p["playing"], "pos": pos,
                                 "at": now * 1000, "age": round(age * 1000)}
        return out


# ---------------------------------------------------------------------------------------------
# MC mode: Gemma plays the machine. The page sends the song as it stands; the model answers with a
# performance: lane, tempo, key, rows to re-roll, a vocal preset, and sections (scene + bars + pad hits +
# lines, each line with a melody as scale degrees). Pocket TTS speaks the lines and the page runs them
# through the auto-tune, forcing one note at a time from the melody.
# ---------------------------------------------------------------------------------------------
LANES = {
    "glitter": "GLITTER: pluggnb / rage, halftime, 112-126 BPM, major or lydian with maj7 and 9th chords, FM bells, glassy keys, glide 808. Pretty, floaty, melodic.",
    "jerk": "JERK: NY jerk / plugg, 116-128 BPM, minor or phrygian one-chord loops, square plugg lead, detuned pad wash, distorted 808, mangled chops. Fidgety, grimy.",
    "che": "CHE: dark jerk / rage, 118-130 BPM, phrygian, one or two chords, 808 into the clipper, rage stabs, sub-octave drone, chops pitched down and reversed. Menacing.",
    "prttifun": "PRTTIFUN: bubblegum plugg, 114-126 BPM, major / lydian pop loops, flute lead, chipmunk chops an octave up, sped-up choir. Sweet, bouncy, bright.",
}
PADS = ["riser", "reverse crash", "boom", "tape stop (the beat winds down and drops back in on the next bar)", "laser", "sparkle", "vox hit", "808 dive"]
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODES = ["major", "lydian", "minor", "dorian", "phrygian", "harmonic"]
ROWS = ["kick", "bass", "snare", "hat", "ohat", "perc", "keys", "lead", "chop", "flip"]
LINE = {"type": "object", "properties": {
    "text": {"type": "string", "maxLength": 70},
    "melody": {"type": "array", "minItems": 2, "maxItems": 12, "items": {"type": "integer", "minimum": -3, "maximum": 9}}},
    "required": ["text", "melody"]}


def section(scenes, min_lines):
    return {"type": "object", "properties": {
        "scene": {"enum": scenes},
        "bars": {"enum": [4, 8]},
        "sung": {"type": "boolean"},
        "pads": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
            "bar": {"type": "integer", "minimum": 1, "maximum": 8},
            "pad": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["bar", "pad"]}},
        "lines": {"type": "array", "minItems": min_lines, "maxItems": 4, "items": LINE}},
        "required": ["scene", "bars", "sung", "pads", "lines"]}


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 40},
        "lane": {"enum": list(LANES)},
        "bpm": {"type": "integer", "minimum": 60, "maximum": 200},
        "key": {"enum": NOTES},
        "mode": {"enum": MODES},
        "swing": {"type": "integer", "minimum": 0, "maximum": 25},
        "reroll": {"type": "array", "maxItems": 4, "items": {"enum": ROWS}},
        "vocal": {"type": "object", "properties": {
            "pitch": {"type": "integer", "minimum": -7, "maximum": 7},
            "formant": {"type": "integer", "minimum": -4, "maximum": 4},
            "double": {"type": "integer", "minimum": 0, "maximum": 100},
            "dirt": {"type": "integer", "minimum": 0, "maximum": 100},
            "delay": {"type": "integer", "minimum": 0, "maximum": 100},
            "verb": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["pitch", "formant", "double", "dirt", "delay", "verb"]},
        "voice": {"type": "string"},
        "sections": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"anyOf": [
            section(["verse", "hook"], 2),      # a verse or a hook always has lines
            section(["intro", "break"], 0)]}},  # an intro or a break may be bare
    },
    "required": ["title", "lane", "bpm", "key", "mode", "swing", "reroll", "vocal", "voice", "sections"],
}
SYSTEM = """You are the MC and producer at an Underground Rap Machine: a browser instrument that generates a
beat and auto-tunes a voice over it. You are given the beat as it stands and you answer with ONE JSON
performance plan, nothing else.

What you control
- lane: the sound template. """ + " ".join(LANES.values()) + """
  Switching lane generates a fresh beat in that lane; keeping it keeps the current beat.
- bpm, key, mode, swing (percent): the groove. The tempo is the performer's call: the message gives a
  tempo zone around the BPM they set, stay inside it. The BPM ranges in the lane descriptions are only
  where each lane usually sits; any lane can be played slower or faster, so pick the lane for the mood
  and keep the performer's tempo.
- reroll: rows of the 16-step pattern to re-roll (kick bass snare hat ohat perc keys lead chop flip).
- vocal: the auto-tune preset for the voice. pitch and formant in semitones. double/dirt/delay/verb 0-100.
- voice: the name of the Pocket TTS voice that sings, from the list given.
- sections: the arrangement, played in order. scene is a mute group: intro (keys and flip only, filtered),
  verse (no chops, no lead), hook (everything), break (no drums). bars is 4 or 8. pads are one-shots fired
  on a bar of the section (bar 1 = its first bar); pad numbers: """ + ", ".join(f"{i+1} {p}" for i, p in enumerate(PADS)) + """.
  Use tape stop at most once, as a drop on the last bar before a hook or on the very last bar.
- sung: true to SING the section, false to RAP it. A sung line is held out on the beat: one vowel per
  syllable on quarters or eighths over two bars, the last syllable held, at the melody's pitch; a rapped
  line is spoken in rhythm and the auto-tune bends it onto the melody. Sing a hook to make it catchy, rap
  the verses; a sung bridge or outro is a nice turn.
- lines: the lyrics of the section, one after another from its first bar. Each line is 4 to 9 words,
  one breath. Its melody is the notes the auto-tune forces, as scale degrees: 0 is the root, 2 the third,
  4 the fifth, 7 the octave, negative goes below the root. For a rapped line give 2 to 8 degrees, spread
  evenly over it. For a sung line give ONE DEGREE PER SYLLABLE (up to 12), a tune someone could hum: mostly
  steps, a leap to land the line, end on 0, 2 or 4. Hooks repeat a shape; verses move more.

Write like the lane: GLITTER is dreamy and flexing, JERK is jittery NY slang, CHE is paranoid and dark,
PRTTIFUN is sugary and playful. Hooks come back word for word. Rhyme inside and at the ends of lines.
Original words only: never quote existing songs and never name real artists. Slang and swearing are fine;
no slurs, nothing hateful. An intro or break may have no lines; a hook and a verse always have lines.
Eight to twelve lines in the whole plan. Write the JSON compact, on one line, no spaces after commas."""

SING = {
    "auto": "Singing: your call; sing at least one section (a hook is the natural one) and rap at least one.\n",
    "hooks": "Singing: every hook is sung (sung true); verses, intros and breaks are rapped (sung false).\n",
    "all": "Singing: sing every section (sung true everywhere), short lines with few syllables, like a ballad.\n",
    "off": "Singing: none; rap every section (sung false everywhere).\n",
}
# the performer's tempo baseline (one tap on the page): the song is written for it, not just played at it
FEEL = {
    "uptempo": "Feel: uptempo, around 160 BPM. A bar goes by in 1.5 s, so keep lines short and punchy (6-9 syllables), "
               "with hype, quick-fire energy and chants that land on the beat.\n",
    "downtempo": "Feel: downtempo, around 120 BPM. Lines have room to breathe: laid-back flows, longer lines (8-12 "
                 "syllables), moodier and more melodic.\n",
}


class AIBridge:
    def __init__(self, llm, tts, voice, model=None):
        self.llm, self.tts, self.voice = llm.rstrip("/") if llm else None, tts.rstrip("/") if tts else None, voice
        if self.llm and self.llm.endswith("/v1"):
            self.llm = self.llm[:-3]
        self.model = model   # sent with every request; llama-server serves one model and needs none
        self.progress = {"phase": "idle"}
        self.tts_state = {"busy": 0, "x": None}   # how many lines are being sung, last audio-seconds per wall-second
        self.lock = threading.Lock()
        self.job, self.job_thread, self.result = 0, None, None   # plans run in a thread; the page polls

    def start_plan(self, req):
        """Begin writing a plan in the background and return its job number at once. A plan takes a minute
        or two, too long to hold one HTTP request open: the page polls /ai/progress and then fetches the
        result from /ai/plan?job=N. A job already running is handed back instead of starting a second."""
        if not self.llm:
            return {"error": "no LLM configured (server.py --llm URL)"}
        with self.lock:
            if self.job_thread and self.job_thread.is_alive():
                return {"job": self.job, "running": True}
            self.job += 1
            job = self.job
            self.progress = {"phase": "prompt", "tokens": 0, "t0": time.time(), "job": job}
            self.result = None
            self.job_thread = threading.Thread(target=self._run_plan, args=(job, req), daemon=True)
            self.job_thread.start()
        return {"job": job}

    def _run_plan(self, job, req):
        try:
            res = self.plan(req, job)
        except Exception as e:  # noqa: BLE001
            res = {"error": str(e)}
            with self.lock:
                self.progress = {"phase": "error", "error": str(e), "job": job}
        with self.lock:
            self.result = (job, res)
            if "plan" in res:
                self.progress = {"phase": "done", "tokens": res["tokens"], "secs": res["secs"], "job": job}

    def fetch_plan(self, job):
        with self.lock:
            if self.result and self.result[0] == job:
                return self.result[1]
            return {"error": "no such plan" if job != self.job else "still writing"}

    def _get(self, url, timeout=3):
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def health(self):
        out = {"llm": False, "tts": False, "model": None, "voices": [], "voice": self.voice, "llmUrl": self.llm, "ttsUrl": self.tts}
        if self.llm:
            try:
                h = self._get(self.llm + "/health")
                out["llm"] = h.get("status") == "ok"
                out["llmStatus"] = h.get("status")
            except urllib.error.HTTPError as e:
                out["llmStatus"] = "loading" if e.code == 503 else f"http {e.code}"
                if e.code == 404:   # not llama-server (Ollama, a proxy): up if it lists its models
                    try:
                        self._get(self.llm + "/v1/models")
                        out["llm"], out["llmStatus"] = True, "ok"
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                out["llmStatus"] = "down"
            if out["llm"] and self.model:
                out["model"] = self.model
            elif out["llm"]:
                try:
                    m = self._get(self.llm + "/v1/models")
                    out["model"] = os.path.basename((m.get("data") or [{}])[0].get("id", "")) or None
                except Exception:  # noqa: BLE001
                    pass
        if self.tts:
            try:
                v = self._get(self.tts + "/v1/audio/voices")
                out["voices"] = [x.get("name") for x in v.get("voices", []) if isinstance(x, dict) and x.get("name")]
                out["tts"] = True
            except Exception:  # noqa: BLE001
                pass
        return out

    def plan(self, req, job=0):
        """One streamed chat completion, constrained to PLAN_SCHEMA. req: {state, theme, avoid, voices}."""
        if not self.llm:
            return {"error": "no LLM configured (server.py --llm URL)"}
        st = req.get("state") or {}
        voices = req.get("voices") or ["alba"]
        avoid = [t for t in (req.get("avoid") or []) if t][-6:]
        theme = (req.get("theme") or "surprise me").strip()[:60]
        tempo = req.get("tempo") or {}
        try:
            anchor = int(tempo.get("anchor") or st.get("bpm") or 120)
        except (TypeError, ValueError):
            anchor = 120
        margin = max(4, round(anchor * 0.05))
        lo, hi = int(tempo.get("lo") or anchor - margin), int(tempo.get("hi") or anchor + margin)
        sing = req.get("sing") or "auto"
        try:
            sync_pct = max(0, min(100, int(req.get("sync", 45))))
        except (TypeError, ValueError):
            sync_pct = 45
        user = (
            f"The beat right now: lane {st.get('lane')}, {st.get('bpm')} BPM, {st.get('key')} {st.get('mode')}, "
            f"chords {' | '.join(st.get('chords') or [])}, swing {st.get('swing')}%, scene {st.get('scene')}. "
            f"Steps on per row: {st.get('density')}.\n"
            f"Tempo zone: {lo}-{hi} BPM, set by the performer around {anchor}; bpm must stay inside it.\n"
            + FEEL.get(tempo.get("feel"), "")
            + f"Vocal syncopation {sync_pct}%: "
            + ("every line lands square on the downbeat, so write even lines of the same length.\n" if sync_pct < 20 else
               "lines come in on pickups and behind the beat; mix short punchy lines with longer ones and start some on a one-word pickup.\n" if sync_pct >= 60 else
               "some lines come in on a pickup or behind the beat; vary the line lengths a little.\n")
            + SING.get(sing, SING["auto"])
            + f"Voices available: {', '.join(voices)}.\n"
            f"Theme from the performer: {theme}.\n"
            + (f"Already performed this session: {'; '.join(avoid)}. Do not reuse those titles or lines; change the key, the lane or the mood.\n" if avoid else "")
            + "Answer with the JSON plan."
        )
        body = {
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "stream": True, "temperature": 0.9, "top_p": 0.95, "max_tokens": 1400,
            "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "schema": PLAN_SCHEMA}},
            "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none",
        }
        if self.model:
            body["model"] = self.model
        t0 = time.time()
        with self.lock:
            self.progress = {"phase": "prompt", "tokens": 0, "t0": t0, "job": job}
        text, tokens = "", 0
        try:
            rq = urllib.request.Request(self.llm + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=900) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        ev = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    for ch in ev.get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content")
                        if piece:
                            text += piece
                            tokens += 1
                            with self.lock:
                                self.progress = {"phase": "writing", "tokens": tokens, "t0": t0, "secs": time.time() - t0, "job": job}
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode("utf-8", "replace")
            with self.lock:
                self.progress = {"phase": "error", "error": f"llm http {e.code}: {msg}", "job": job}
            return {"error": f"llm http {e.code}: {msg}"}
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.progress = {"phase": "error", "error": str(e), "job": job}
            return {"error": str(e)}
        try:
            a, b = text.index("{"), text.rindex("}") + 1
            plan = json.loads(text[a:b])
        except (ValueError, json.JSONDecodeError) as e:
            with self.lock:
                self.progress = {"phase": "error", "error": "bad JSON from the model", "job": job}
            return {"error": f"bad JSON from the model: {e}", "raw": text[:2000]}
        secs = time.time() - t0
        print(f"plan: {plan.get('title')!r} lane={plan.get('lane')} {tokens} tokens in {secs:.0f}s", flush=True)
        return {"plan": plan, "tokens": tokens, "secs": secs}   # _run_plan stores it, then marks the job done

    def speak(self, text, voice):
        if not self.tts:
            raise RuntimeError("no TTS configured (server.py --tts URL)")
        body = json.dumps({"input": text, "voice": voice or self.voice, "response_format": "wav"}).encode()
        rq = urllib.request.Request(self.tts + "/v1/audio/speech", body, {"Content-Type": "application/json"})
        t0 = time.time()
        with self.lock:
            self.tts_state["busy"] += 1
        try:
            with urllib.request.urlopen(rq, timeout=180) as r:
                wav = r.read()
        finally:
            with self.lock:
                self.tts_state["busy"] -= 1
        secs = time.time() - t0
        if len(wav) > 44 and secs > 0:   # 24 kHz mono 16-bit from Pocket TTS
            with self.lock:
                self.tts_state["x"] = round((len(wav) - 44) / 48000 / secs, 2)
        return wav


def battery():
    """Charge state of the device battery from sysfs, or None when there is none (a desktop)."""
    base = "/sys/class/power_supply"
    out = {}
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for d in names:
        def rd(f, d=d):
            try:
                with open(os.path.join(base, d, f)) as fh:
                    return fh.read().strip()
            except OSError:
                return None
        kind = rd("type")
        if kind == "Battery":
            cap, st, i, v, pw = rd("capacity"), rd("status"), rd("current_now"), rd("voltage_now"), rd("power_now")
            try:
                w = abs(int(pw)) / 1e6 if pw else abs(int(i)) * int(v) / 1e12 if i and v else None
            except ValueError:
                w = None
            out.update({"pct": int(cap) if cap and cap.isdigit() else None, "status": st, "w": round(w, 1) if w is not None else None})
        elif kind in ("USB", "Mains", "USB_PD") and rd("online") not in (None, "0"):
            out["ac"] = True
    return out or None


def make_handler(state, directory):
    class H(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"   # keep-alive: the page posts LED frames ~30 times a second

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, fmt, *args):
            if self.path.startswith(("/led", "/status", "/cmd", "/sys", "/link", "/sync", "/ai/progress", "/ai/health")):
                return
            super().log_message(fmt, *args)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/status":
                with state.lock:
                    return self._json(200, state.status)
            if path == "/link":
                with state.lock:
                    return self._json(200, state.link or {})
            if path == "/sync":
                return self._json(200, state.sync.view() if state.sync else {"mode": "off", "peers": [], "leader": None, "unavailable": True})
            if path == "/ai/health":
                return self._json(200, state.ai.health())
            if path == "/ai/progress":
                with state.ai.lock:
                    return self._json(200, state.ai.progress)
            if path == "/ai/plan":   # ?job=N: the finished plan of that job
                try:
                    job = int(self.path.split("job=")[1].split("&")[0])
                except (IndexError, ValueError):
                    return self._json(400, {"error": "job=N needed"})
                res = state.ai.fetch_plan(job)
                return self._json(200 if "plan" in res else 404, res)
            if path == "/sys":   # the handheld's battery gauge and Gemma speedo
                with state.ai.lock:
                    prog, tts = dict(state.ai.progress), dict(state.ai.tts_state)
                if prog.get("phase") == "writing" and prog.get("secs"):
                    prog["tps"] = round(prog["tokens"] / prog["secs"], 1)
                prog.pop("t0", None)
                return self._json(200, {"bat": battery(), "out": state.phones.out, "llm": bool(state.ai.llm), "ai": prog, "tts": tts})
            if path == "/cmd":
                wait = 20.0
                if "wait=" in self.path:
                    try:
                        wait = float(self.path.split("wait=")[1].split("&")[0])
                    except ValueError:
                        pass
                with state.cv:
                    if not state.cmds:
                        state.cv.wait(min(wait, 25))
                    out, state.cmds = state.cmds, []
                return self._json(200, out)
            return super().do_GET()

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                data = self._body()
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"error": "bad json"})
            if path == "/led":
                if not state.rings.ok:
                    return self._json(503, {"error": "no LEDs"})
                try:
                    with state.lock:
                        state.rings.set(data)
                except (KeyError, TypeError, ValueError, OSError) as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {})
            if path == "/status":
                with state.lock:
                    state.status = data
                return self._json(200, {})
            if path == "/link":
                with state.lock:
                    state.link, state.link_t = data, time.time()
                return self._json(200, {})
            if path == "/sync":
                if not state.sync:
                    return self._json(503, {"error": "sync is off (--sync-port 0) or its port is taken"})
                if data.get("mode") not in ("off", "auto", "lead", "follow"):
                    return self._json(400, {"error": "mode is off, auto, lead or follow"})
                state.sync.mode = data["mode"]
                return self._json(200, state.sync.view())
            if path == "/cmd":
                with state.cv:
                    state.cmds.append(data)
                    state.cv.notify_all()
                return self._json(200, {"queued": len(state.cmds)})
            if path == "/ai/plan":
                res = state.ai.start_plan(data)
                return self._json(200 if "job" in res else 502, res)
            if path == "/ai/tts":
                try:
                    wav = state.ai.speak(str(data.get("text", ""))[:200], data.get("voice"))
                except Exception as e:  # noqa: BLE001
                    return self._json(502, {"error": str(e)})
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self.end_headers()
                self.wfile.write(wav)
                return None
            return self._json(404, {"error": "no such endpoint"})

    return H


def serve(port, directory, ai, link_port=47800, sync_port=5150, sync_mode="auto"):
    state = State(ai)
    threading.Thread(target=state.phones.run, daemon=True).start()
    if link_port:
        threading.Thread(target=beacon, args=(state, link_port), daemon=True).start()
    if sync_port:
        sync = Sync(state, sync_port, sync_mode)
        try:
            sync.open()
            state.sync = sync
            threading.Thread(target=sync.run, daemon=True).start()
        except OSError as e:
            print(f"sync: UDP {sync_port} unavailable ({e}); running without it", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, directory))
    srv.daemon_threads = True

    def bye(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f"rap machine bridge on http://127.0.0.1:{port}/ serving {directory}; LEDs {'on' if state.rings.ok else 'off'}; "
          f"LLM {ai.llm or 'none'}; TTS {ai.tts or 'none'}; jam link {f'UDP {link_port}' if link_port else 'off'}; "
          f"sync {f'UDP {sync_port} {state.sync.mode}' if state.sync else 'off'}", flush=True)
    try:
        srv.serve_forever()
    finally:
        state.rings.restore()
        state.phones.restore()
        print("rings restored", flush=True)


def test_order():
    rings = Rings()
    if not rings.ok:
        sys.exit(1)
    try:
        for side, ring in (("left", rings.l), ("right", rings.r)):
            for i, n in enumerate(ORDER[side[0]]):
                cols = [[0, 0, 0]] * 4
                cols[i] = [255, 255, 255]
                ring.set(cols)
                print(f"{side} ring: position {i} (clockwise from the top) = rgb:{side[0]}{n}", flush=True)
                time.sleep(1.5)
            ring.set([[0, 0, 0]] * 4)
    finally:
        rings.restore()


def send(port, path, obj=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if obj is not None else "GET",
                                 data=None if obj is None else json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def grant_mic(port):
    """Firefox keeps site permissions in moz_perms; a row with permission 1 is Allow, no expiry."""
    if os.path.exists("/storage/apps/firefox-rocknix/firefox.pid"):
        sys.exit("Firefox is running (firefox.pid exists); close it first")
    db = f"{PROFILE}/permissions.sqlite"
    if not os.path.exists(db):
        sys.exit(f"{db} not found")
    origin = f"http://127.0.0.1:{port}"
    con = sqlite3.connect(db)
    try:
        for typ in ("microphone",):
            have = con.execute("select permission from moz_perms where origin=? and type=?", (origin, typ)).fetchone()
            if have and have[0] == 1:
                print(f"{typ} already allowed for {origin}")
                continue
            con.execute("delete from moz_perms where origin=? and type=?", (origin, typ))
            con.execute("insert into moz_perms (origin,type,permission,expireType,expireTime,modificationTime) values (?,?,1,0,0,?)",
                        (origin, typ, int(time.time() * 1000)))
            print(f"{typ} allowed for {origin}")
        con.commit()
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--dir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--test", action="store_true", help="light each ring segment in turn")
    ap.add_argument("--key", help="send a key press to the page (?remote)")
    ap.add_argument("--click", help="click a CSS selector on the page (?remote)")
    ap.add_argument("--set", nargs=2, metavar=("SELECTOR", "VALUE"), help="set an input's value on the page (?remote)")
    ap.add_argument("--status", action="store_true", help="print the page's last heartbeat")
    ap.add_argument("--grant-mic", action="store_true", help="allow the mic for this origin in the house Firefox profile")
    ap.add_argument("--llm", default=os.environ.get("URM_LLM"), help="llama-server base URL for the MC mode")
    ap.add_argument("--llm-model", default=os.environ.get("URM_LLM_MODEL"), help="model to ask for, for a server that hosts several (Ollama)")
    ap.add_argument("--tts", default=os.environ.get("URM_TTS"), help="tts-server (Pocket TTS) base URL for the MC mode")
    ap.add_argument("--voice", default=os.environ.get("URM_VOICE", "alba"), help="default Pocket TTS voice")
    ap.add_argument("--link-port", type=int, default=int(os.environ.get("URM_LINK_PORT", "47800")),
                    help="UDP port of the jam-link beacon on the LAN (0 = off)")
    ap.add_argument("--sync-port", type=int, default=int(os.environ.get("URM_SYNC_PORT", "5150")),
                    help="UDP port of the HI5S Wi-Fi sync with HI5, Jaffedrone and fliptribe (0 = off)")
    ap.add_argument("--sync", default=os.environ.get("URM_SYNC", "auto"), choices=["off", "auto", "lead", "follow"],
                    help="sync role at start: the page can change it (default auto: the lowest id leads)")
    a = ap.parse_args()
    if a.test:
        return test_order()
    if a.grant_mic:
        return grant_mic(a.port)
    if a.key or a.click or a.set:
        cmd = {}
        if a.key:
            cmd["key"] = a.key
        if a.click:
            cmd["click"] = a.click
        if a.set:
            cmd["set"] = a.set
        return print(send(a.port, "/cmd", cmd))
    if a.status:
        return print(json.dumps(send(a.port, "/status"), indent=1))
    serve(a.port, a.dir, AIBridge(a.llm, a.tts, a.voice, a.llm_model), a.link_port, a.sync_port, a.sync)


if __name__ == "__main__":
    main()
