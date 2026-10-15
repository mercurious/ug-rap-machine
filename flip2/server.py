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

The rings are restored to what they showed before when the server exits.
"""
import argparse, json, os, signal, sqlite3, sys, threading, time, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

LED_ROOT = "/sys/class/leds"
# Which sysfs segment (rgb:l1..4 / rgb:r1..4) sits where on each ring, clockwise from the top.
# Verify with --test and fix here if the clock runs the wrong way round.
ORDER = {"l": [1, 2, 3, 4], "r": [1, 2, 3, 4]}
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
    def __init__(self):
        self.rings = Rings()
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.cmds = []
        self.status = {}


def make_handler(state, directory):
    class H(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"   # keep-alive: the page posts LED frames ~30 times a second

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, fmt, *args):
            if self.path.startswith(("/led", "/status", "/cmd")):
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
            return self._json(404, {"error": "no such endpoint"})

    return H


def serve(port, directory):
    state = State()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, directory))
    srv.daemon_threads = True

    def bye(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f"rap machine bridge on http://127.0.0.1:{port}/ serving {directory}; LEDs {'on' if state.rings.ok else 'off'}", flush=True)
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
    serve(a.port, a.dir)


if __name__ == "__main__":
    main()
