#!/usr/bin/env python3
"""Underground Rap Machine bridge for the Retroid Pocket Flip 2 (ROCKNIX).

Serves the app on http://127.0.0.1:PORT (a secure context, so Firefox allows the mic) and drives
the RGB rings around the sticks from the page. Standard library only (ROCKNIX ships python3).

  POST /led     {"l": [[r,g,b] ×4], "r": [[r,g,b] ×4]}  segment colours 0–255, clockwise from the top
  POST /status  any JSON: the page's heartbeat (sent when opened with ?remote); GET /status returns it
  POST /cmd     {"key": "m"} | {"click": "#gen"} | {"set": ["#bpm", 160]}: queued for the page,
                which long-polls GET /cmd?wait=20 when opened with ?remote. Lets ssh drive the page.

  server.py --port 8766 --dir /storage/apps/rap-machine     serve (the launcher does this)
  server.py --test                                           light each segment in turn, to check ORDER
  server.py --key m | --click "#gen" | --set "#bpm" 160      send a command to the running server
  server.py --status                                         print the page's last heartbeat
  server.py --grant-mic                                      allow the mic for this origin in the house
                                                             Firefox profile (Firefox must be closed)
  server.py --llm http://127.0.0.1:8096 --tts http://127.0.0.1:8097
                                                             also bridge Gemma (llama-server) and Pocket TTS
                                                             (tts-server) for the MC mode: POST /ai/plan asks the
                                                             model for a performance (JSON), POST /ai/tts sings a
                                                             line, GET /ai/health and /ai/progress for the page;
  GET /sys                                                   battery and model activity for the views-row gauges

The rings are restored to what they showed before when the server exits.
"""
import argparse, json, os, signal, sqlite3, sys, threading, time, urllib.error, urllib.request
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


# ---------------------------------------------------------------------------------------------
# MC mode: Gemma plays the machine. The page sends the song as it stands; the model answers with a
# performance: lane, tempo, key, rows to re-roll, a vocal preset, and sections (scene + bars + pad hits +
# lines, each line with a melody as scale degrees). Pocket TTS speaks the lines and the page runs them
# through the auto-tune, forcing one note at a time from the melody.
# ---------------------------------------------------------------------------------------------
LANES = {
    "glitter": "GLITTER: pluggnb / rage, halftime, 142-162 BPM, major or lydian with maj7 and 9th chords, FM bells, glassy keys, glide 808. Pretty, floaty, melodic.",
    "jerk": "JERK: NY jerk / plugg, 150-180 BPM, minor or phrygian one-chord loops, square plugg lead, detuned pad wash, distorted 808, mangled chops. Fidgety, grimy.",
    "che": "CHE: dark jerk / rage, 158-176 BPM, phrygian, one or two chords, 808 into the clipper, rage stabs, sub-octave drone, chops pitched down and reversed. Menacing.",
    "prttifun": "PRTTIFUN: bubblegum plugg, 150-170 BPM, major / lydian pop loops, flute lead, chipmunk chops an octave up, sped-up choir. Sweet, bouncy, bright.",
}
PADS = ["riser", "reverse crash", "boom", "tape stop (the beat winds down and drops back in on the next bar)", "laser", "sparkle", "vox hit", "808 dive"]
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODES = ["major", "lydian", "minor", "dorian", "phrygian", "harmonic"]
ROWS = ["kick", "bass", "snare", "hat", "ohat", "perc", "keys", "lead", "chop", "flip"]
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 40},
        "lane": {"enum": list(LANES)},
        "bpm": {"type": "integer", "minimum": 135, "maximum": 182},
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
        "sections": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"type": "object", "properties": {
            "scene": {"enum": ["intro", "verse", "hook", "break"]},
            "bars": {"enum": [4, 8]},
            "pads": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
                "bar": {"type": "integer", "minimum": 1, "maximum": 8},
                "pad": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["bar", "pad"]}},
            "lines": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {
                "text": {"type": "string", "maxLength": 70},
                "melody": {"type": "array", "minItems": 2, "maxItems": 8,
                           "items": {"type": "integer", "minimum": -3, "maximum": 9}}},
                "required": ["text", "melody"]}}},
            "required": ["scene", "bars", "pads", "lines"]}},
    },
    "required": ["title", "lane", "bpm", "key", "mode", "swing", "reroll", "vocal", "voice", "sections"],
}
SYSTEM = """You are the MC and producer at an Underground Rap Machine: a browser instrument that generates a
beat and auto-tunes a voice over it. You are given the beat as it stands and you answer with ONE JSON
performance plan, nothing else.

What you control
- lane: the sound template. """ + " ".join(LANES.values()) + """
  Switching lane generates a fresh beat in that lane; keeping it keeps the current beat.
- bpm, key, mode, swing (percent): the groove. Stay inside the lane's tempo range.
- reroll: rows of the 16-step pattern to re-roll (kick bass snare hat ohat perc keys lead chop flip).
- vocal: the auto-tune preset for the voice. pitch and formant in semitones. double/dirt/delay/verb 0-100.
- voice: the name of the Pocket TTS voice that sings, from the list given.
- sections: the arrangement, played in order. scene is a mute group: intro (keys and flip only, filtered),
  verse (no chops, no lead), hook (everything), break (no drums). bars is 4 or 8. pads are one-shots fired
  on a bar of the section (bar 1 = its first bar); pad numbers: """ + ", ".join(f"{i+1} {p}" for i, p in enumerate(PADS)) + """.
  Use tape stop at most once, as a drop on the last bar before a hook or on the very last bar.
- lines: the lyrics of the section, sung one after another from its first bar. Each line is 4 to 9 words,
  one breath. Its melody is the notes the auto-tune forces, as scale degrees spread evenly over the line:
  0 is the root, 2 the third, 4 the fifth, 7 the octave, negative goes below the root. Hooks repeat a
  shape; verses move more. Give every line 2 to 8 degrees.

Write like the lane: GLITTER is dreamy and flexing, JERK is jittery NY slang, CHE is paranoid and dark,
PRTTIFUN is sugary and playful. Hooks come back word for word. Rhyme inside and at the ends of lines.
Original words only: never quote existing songs and never name real artists. Slang and swearing are fine;
no slurs, nothing hateful. An intro or break may have no lines; a hook and a verse always have lines.
Eight to twelve lines in the whole plan. Write the JSON compact, on one line, no spaces after commas."""


class AIBridge:
    def __init__(self, llm, tts, voice):
        self.llm, self.tts, self.voice = llm.rstrip("/") if llm else None, tts.rstrip("/") if tts else None, voice
        self.progress = {"phase": "idle"}
        self.tts_state = {"busy": 0, "x": None}   # how many lines are being sung, last audio-seconds per wall-second
        self.lock = threading.Lock()

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
            except Exception:  # noqa: BLE001
                out["llmStatus"] = "down"
            if out["llm"]:
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

    def plan(self, req):
        """One streamed chat completion, constrained to PLAN_SCHEMA. req: {state, theme, avoid, voices}."""
        if not self.llm:
            return {"error": "no LLM configured (server.py --llm URL)"}
        st = req.get("state") or {}
        voices = req.get("voices") or ["alba"]
        avoid = [t for t in (req.get("avoid") or []) if t][-6:]
        theme = (req.get("theme") or "surprise me").strip()[:60]
        user = (
            f"The beat right now: lane {st.get('lane')}, {st.get('bpm')} BPM, {st.get('key')} {st.get('mode')}, "
            f"chords {' | '.join(st.get('chords') or [])}, swing {st.get('swing')}%, scene {st.get('scene')}. "
            f"Steps on per row: {st.get('density')}.\n"
            f"Voices available: {', '.join(voices)}.\n"
            f"Theme from the performer: {theme}.\n"
            + (f"Already performed this session: {'; '.join(avoid)}. Do not reuse those titles or lines; change the key, the lane or the mood.\n" if avoid else "")
            + "Answer with the JSON plan."
        )
        body = {
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "stream": True, "temperature": 0.9, "top_p": 0.95, "max_tokens": 1400,
            "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "schema": PLAN_SCHEMA}},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        t0 = time.time()
        with self.lock:
            self.progress = {"phase": "prompt", "tokens": 0, "t0": t0}
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
                                self.progress = {"phase": "writing", "tokens": tokens, "t0": t0, "secs": time.time() - t0}
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode("utf-8", "replace")
            with self.lock:
                self.progress = {"phase": "error", "error": f"llm http {e.code}: {msg}"}
            return {"error": f"llm http {e.code}: {msg}"}
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.progress = {"phase": "error", "error": str(e)}
            return {"error": str(e)}
        try:
            a, b = text.index("{"), text.rindex("}") + 1
            plan = json.loads(text[a:b])
        except (ValueError, json.JSONDecodeError) as e:
            with self.lock:
                self.progress = {"phase": "error", "error": "bad JSON from the model"}
            return {"error": f"bad JSON from the model: {e}", "raw": text[:2000]}
        secs = time.time() - t0
        with self.lock:
            self.progress = {"phase": "done", "tokens": tokens, "secs": secs}
        print(f"plan: {plan.get('title')!r} lane={plan.get('lane')} {tokens} tokens in {secs:.0f}s", flush=True)
        return {"plan": plan, "tokens": tokens, "secs": secs}

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
            if self.path.startswith(("/led", "/status", "/cmd", "/sys", "/ai/progress", "/ai/health")):
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
            if path == "/ai/health":
                return self._json(200, state.ai.health())
            if path == "/ai/progress":
                with state.ai.lock:
                    return self._json(200, state.ai.progress)
            if path == "/sys":   # the battery gauge and the Gemma speedo in the handheld's views row
                with state.ai.lock:
                    prog, tts = dict(state.ai.progress), dict(state.ai.tts_state)
                if prog.get("phase") == "writing" and prog.get("secs"):
                    prog["tps"] = round(prog["tokens"] / prog["secs"], 1)
                prog.pop("t0", None)
                return self._json(200, {"bat": battery(), "llm": bool(state.ai.llm), "ai": prog, "tts": tts})
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
            if path == "/cmd":
                with state.cv:
                    state.cmds.append(data)
                    state.cv.notify_all()
                return self._json(200, {"queued": len(state.cmds)})
            if path == "/ai/plan":
                res = state.ai.plan(data)
                return self._json(200 if "plan" in res else 502, res)
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


def serve(port, directory, ai):
    state = State(ai)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, directory))
    srv.daemon_threads = True

    def bye(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f"rap machine bridge on http://127.0.0.1:{port}/ serving {directory}; LEDs {'on' if state.rings.ok else 'off'}; "
          f"LLM {ai.llm or 'none'}; TTS {ai.tts or 'none'}", flush=True)
    try:
        srv.serve_forever()
    finally:
        state.rings.restore()
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
    ap.add_argument("--tts", default=os.environ.get("URM_TTS"), help="tts-server (Pocket TTS) base URL for the MC mode")
    ap.add_argument("--voice", default=os.environ.get("URM_VOICE", "alba"), help="default Pocket TTS voice")
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
    serve(a.port, a.dir, AIBridge(a.llm, a.tts, a.voice))


if __name__ == "__main__":
    main()
