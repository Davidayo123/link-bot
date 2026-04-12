"""
Link Bot — Cloud-hosted bot with a mobile-friendly dashboard.

Visits a URL silently every N minutes using HTTP requests.
Control it from your phone via the web dashboard.
Protected by a PIN code.

Environment Variables (set these on Render):
    BOT_PIN          — Dashboard PIN (default: 1234)
    SECRET_KEY       — Flask session secret (change in production)
    RENDER_EXTERNAL_URL — Auto-set by Render, used for self-ping
"""

import os
import time
import random
import threading
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session


# ─── App Setup ───────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bot-secret-change-in-production-xyz")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ─── Configuration ───────────────────────────────────────────────
BOT_PIN = os.environ.get("BOT_PIN", "1234")
DEFAULT_URL = (
    "https://www.novelol.com/goodnovel/share?"
    "bid=31001345199&uid=228913354&l=bookDetail"
    "&sc=fxrw_0_bookDetail&rd=4&type=3"
)
DEFAULT_INTERVAL = 10  # minutes

# Realistic browser User-Agent strings (rotated randomly)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Bot Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BotEngine:
    """Background worker that visits a URL at a configurable interval."""

    def __init__(self):
        self.url = DEFAULT_URL
        self.interval = DEFAULT_INTERVAL
        self.status = "stopped"
        self.visit_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.last_visit = None
        self.next_visit = None
        self.started_at = None
        self.log = []
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    # ── Logging ──────────────────────────────────────────────────
    def _log(self, level, msg):
        with self._lock:
            self.log.insert(0, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "level": level,
                "msg": msg,
            })
            if len(self.log) > 200:
                self.log = self.log[:200]

    # ── Visit logic ──────────────────────────────────────────────
    def _visit(self):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
            resp = http_requests.get(
                self.url, headers=headers, timeout=30, allow_redirects=True
            )
            with self._lock:
                self.visit_count += 1
                self.success_count += 1
                self.last_visit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log("success", f"Visit #{self.visit_count} — HTTP {resp.status_code}")
        except http_requests.RequestException as e:
            with self._lock:
                self.visit_count += 1
                self.fail_count += 1
            self._log("error", f"Visit failed — {str(e)[:80]}")

    # ── Main loop ────────────────────────────────────────────────
    def _loop(self):
        self._log("info", "Bot started")
        while not self._stop.is_set():
            # If paused, spin-wait
            if self._pause.is_set():
                time.sleep(1)
                continue

            self._visit()

            with self._lock:
                self.next_visit = (
                    datetime.now() + timedelta(minutes=self.interval)
                ).strftime("%Y-%m-%d %H:%M:%S")

            # Sleep in 1s chunks for responsiveness
            for _ in range(self.interval * 60):
                if self._stop.is_set() or self._pause.is_set():
                    break
                time.sleep(1)

        with self._lock:
            self.next_visit = None
        self._log("info", "Bot stopped")

    # ── Controls ─────────────────────────────────────────────────
    def start(self):
        if self.status == "running":
            return {"ok": False, "msg": "Already running"}
        self._stop.clear()
        self._pause.clear()
        self.status = "running"
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return {"ok": True, "msg": "Bot started"}

    def stop(self):
        if self.status == "stopped":
            return {"ok": False, "msg": "Already stopped"}
        self._stop.set()
        self._pause.clear()
        self.status = "stopped"
        self.started_at = None
        with self._lock:
            self.next_visit = None
        return {"ok": True, "msg": "Bot stopped"}

    def toggle_pause(self):
        if self.status == "stopped":
            return {"ok": False, "msg": "Bot is not running"}
        if self._pause.is_set():
            self._pause.clear()
            self.status = "running"
            self._log("info", "Bot resumed")
            return {"ok": True, "msg": "Resumed"}
        else:
            self._pause.set()
            self.status = "paused"
            with self._lock:
                self.next_visit = None
            self._log("info", "Bot paused")
            return {"ok": True, "msg": "Paused"}

    def update_settings(self, url=None, interval=None):
        changes = []
        if url and url.strip():
            self.url = url.strip()
            changes.append("URL")
        if interval is not None:
            try:
                val = max(1, int(interval))
                self.interval = val
                changes.append(f"interval → {val}min")
            except (ValueError, TypeError):
                pass
        if changes:
            self._log("info", f"Settings updated: {', '.join(changes)}")
        return {"ok": True, "msg": f"Updated: {', '.join(changes)}" if changes else "No changes"}

    def get_status(self):
        with self._lock:
            return {
                "status": self.status,
                "url": self.url,
                "interval": self.interval,
                "visitCount": self.visit_count,
                "successCount": self.success_count,
                "failCount": self.fail_count,
                "lastVisit": self.last_visit,
                "nextVisit": self.next_visit,
                "startedAt": self.started_at,
                "log": self.log[:50],
            }


# ─── Global bot instance ────────────────────────────────────────
bot = BotEngine()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Self-Ping (keeps Render free tier alive)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _self_ping():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        return  # Not deployed on Render — skip
    while True:
        time.sleep(600)
        try:
            http_requests.get(f"{render_url}/health", timeout=10)
        except Exception:
            pass

threading.Thread(target=_self_ping, daemon=True).start()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _authed():
    return session.get("auth") is True


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/login", methods=["POST"])
def api_login():
    pin = str((request.get_json() or {}).get("pin", ""))
    if pin == BOT_PIN:
        session["auth"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Wrong PIN"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("auth", None)
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(bot.get_status())


@app.route("/api/start", methods=["POST"])
def api_start():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(bot.start())


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(bot.stop())


@app.route("/api/pause", methods=["POST"])
def api_pause():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(bot.toggle_pause())


@app.route("/api/settings", methods=["POST"])
def api_settings():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json() or {}
    return jsonify(bot.update_settings(
        url=data.get("url"),
        interval=data.get("interval"),
    ))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Entry Point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Link Bot running at http://localhost:{port}")
    print(f"  Default PIN: {BOT_PIN}\n")
    app.run(host="0.0.0.0", port=port, debug=False)