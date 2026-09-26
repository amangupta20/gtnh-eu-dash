#!/usr/bin/env python3
"""gtnh-eu-dash: EU-only wireless dashboard. Receiver + API + UI. Stdlib only.

Endpoints:
  POST /ingest        {t?, wireless_eu: "<digits>"}  Bearer auth  -> 200/401/400/429
  GET  /api/current   latest sample + EU/t over 5m/1h/24h (server-side int math)
  GET  /api/series?window=5m|1h|24h|7d|30d&points=N   bucketed chart data
  GET  /             the dashboard UI
  GET  /healthz

Env: TOKEN (required) | PORT=8099 | DATA_DIR=/data | RAW_DAYS=90
"""
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("PORT", "8099"))
TOKEN = os.environ.get("TOKEN", "")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "eu.db")
RAW_DAYS = int(os.environ.get("RAW_DAYS", "90"))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
MIN_GAP = 3.0  # min seconds between ingests (OC posts every 10s)
STALE_AFTER = 90  # seconds without a sample before UI shows STALE (3 missed posts)

DIGITS = re.compile(r"^\d{1,40}$")  # up to 40 digits: covers 9e10 -> 6e22 and beyond
WINDOWS = {"5m": 300, "1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000}

os.makedirs(DATA_DIR, exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS samples(ts INTEGER PRIMARY KEY, eu TEXT NOT NULL, eu_f REAL NOT NULL)")
db.commit()
dblock = threading.Lock()
last_ingest = [0.0]


def eut(window_s):
    """EU/t over trailing window using exact int math. None if <2 samples."""
    now = int(time.time())
    with dblock:
        rows = db.execute(
            "SELECT ts, eu FROM samples WHERE ts >= ? ORDER BY ts", (now - window_s,)
        ).fetchall()
    if len(rows) < 2 or rows[-1][0] == rows[0][0]:
        return None
    return (int(rows[-1][1]) - int(rows[0][1])) / (rows[-1][0] - rows[0][0])


def cleanup_loop():
    while True:
        time.sleep(3600)
        with dblock:
            db.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - RAW_DAYS * 86400,))
            db.commit()


class H(BaseHTTPRequestHandler):
    server_version = "eu-dash/1.0"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _static(self, name, ctype):
        p = os.path.join(WEB_DIR, name)
        if not os.path.isfile(p):
            self.send_error(404)
            return
        with open(p, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if u.path == "/healthz":
            return self._json(200, {"ok": True})
        if u.path == "/api/current":
            with dblock:
                row = db.execute("SELECT ts, eu FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
            if not row:
                return self._json(200, {"ts": None, "eu": None, "eut_5m": None, "eut_1h": None, "eut_24h": None, "age_s": None, "stale": True})
            now = int(time.time())
            return self._json(200, {
                "ts": row[0], "eu": row[1],
                "eut_5m": eut(300), "eut_1h": eut(3600), "eut_24h": eut(86400),
                "age_s": now - row[0], "stale": now - row[0] > STALE_AFTER,
            })
        if u.path == "/api/series":
            w = q.get("window", ["24h"])[0]
            try:
                pts = max(2, min(2000, int(q.get("points", ["300"])[0])))
            except ValueError:
                pts = 300
            span = WINDOWS.get(w, 86400)
            start = int(time.time()) - span
            bucket = max(1, span // pts)
            with dblock:
                rows = db.execute(
                    "SELECT (ts/?)*?, AVG(eu_f), COUNT(*) FROM samples WHERE ts>=? GROUP BY 1 ORDER BY 1",
                    (bucket, bucket, start),
                ).fetchall()
            if not rows:
                return self._json(200, {"points": [], "min": None, "max": None})
            vals = [r[1] for r in rows]
            return self._json(200, {
                "points": [[r[0], r[1]] for r in rows], "min": min(vals), "max": max(vals),
            })
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/ingest":
            return self.send_error(404)
        if not TOKEN or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + TOKEN
        ):
            return self._json(401, {"error": "unauthorized"})
        if time.time() - last_ingest[0] < MIN_GAP:
            return self._json(429, {"error": "too fast"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        eu = str(body.get("wireless_eu", ""))
        if not DIGITS.match(eu):
            return self._json(400, {"error": "wireless_eu must be a digit string"})
        ts = int(body.get("t", time.time()))
        if abs(time.time() - ts) > 3600:
            ts = int(time.time())
        eu_f = float(int(eu)) if len(eu) < 309 else float("inf")
        with dblock:
            db.execute(
                "INSERT OR REPLACE INTO samples(ts,eu,eu_f) VALUES(?,?,?)", (ts, eu, eu_f)
            )
            db.commit()
        last_ingest[0] = time.time()
        return self._json(200, {"ok": True, "ts": ts})


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TOKEN env is required")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    print(f"eu-dash on :{PORT} (data: {DB_PATH}, raw retention: {RAW_DAYS}d)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
