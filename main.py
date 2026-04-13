"""
Link Bot — Cloud-hosted bot with a mobile-friendly dashboard.

Uses headless Chrome (Selenium) to realistically browse pages:
  • Loads the full page (JS, CSS, images)
  • Scrolls down gradually for ~10 seconds like a real user
  • Randomises device type, viewport, and User-Agent per visit
  • Routes each visit through a different free proxy for IP diversity

Control it from your phone via the web dashboard.
Protected by a PIN code.

Environment Variables (set these on Render):
    BOT_PIN             — Dashboard PIN (default: 1234)
    SECRET_KEY          — Flask session secret (change in production)
    RENDER_EXTERNAL_URL — Auto-set by Render, used for self-ping
"""

import os
import time
import random
import shutil
import threading
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException


# ─── App Setup ───────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bot-secret-change-in-production-xyz")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Sessions expire after 30 minutes → user must re-enter PIN
app.permanent_session_lifetime = timedelta(minutes=30)

# ─── Configuration ───────────────────────────────────────────────
BOT_PIN = os.environ.get("BOT_PIN", "1234")
DEFAULT_URL = (
    "https://www.novelol.com/goodnovel/share?"
    "bid=31001345199&uid=228913354&l=bookDetail"
    "&sc=fxrw_0_bookDetail&rd=4&type=3"
)
DEFAULT_INTERVAL = 5  # minutes


# ─── Auto-detect Chrome + ChromeDriver ──────────────────────────

def _find_chrome_binary():
    """Search PATH and common locations for a Chrome/Chromium binary."""
    # 1) Check $PATH
    for name in ("chromium", "chromium-browser",
                 "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    # 2) Common absolute paths
    for p in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/lib/chromium/chromium",
    ):
        if os.path.isfile(p):
            return p
    return None


def _find_chromedriver():
    """Search PATH and common locations for the ChromeDriver binary."""
    p = shutil.which("chromedriver")
    if p:
        return p
    for p in (
        "/usr/bin/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ):
        if os.path.isfile(p):
            return p
    return None


# Resolve once at import time and log the results
CHROME_BINARY = _find_chrome_binary()
CHROMEDRIVER_PATH = _find_chromedriver()
print(f"  [Boot] Chrome binary  : {CHROME_BINARY or 'NOT FOUND'}")
print(f"  [Boot] ChromeDriver   : {CHROMEDRIVER_PATH or 'NOT FOUND (will try webdriver-manager)'}")


def _get_chromedriver_service():
    """Return a Selenium Service pointing to ChromeDriver."""
    if CHROMEDRIVER_PATH:
        return Service(CHROMEDRIVER_PATH)
    # Fallback — let webdriver-manager download a matching driver
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        return Service(ChromeDriverManager().install())
    except Exception as exc:
        raise RuntimeError(
            f"Cannot locate ChromeDriver. System path not found and "
            f"webdriver-manager also failed: {exc}"
        )


# ─── Device Profiles (User-Agent + Viewport + Label) ─────────────
DEVICE_PROFILES = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
     "vp": (1920, 1080), "device": "Desktop · Win/Chrome"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
     "vp": (1366, 768), "device": "Laptop · Win/Chrome"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
           "Gecko/20100101 Firefox/125.0",
     "vp": (1536, 864), "device": "Desktop · Win/Firefox"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
     "vp": (1440, 900), "device": "MacBook · Chrome"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
     "vp": (1280, 800), "device": "MacBook · Safari"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
           "Mobile/15E148 Safari/604.1",
     "vp": (390, 844), "device": "iPhone 15"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) "
           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 "
           "Mobile/15E148 Safari/604.1",
     "vp": (430, 932), "device": "iPhone 15 Pro Max"},
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
     "vp": (412, 915), "device": "Pixel 8 Pro"},
    {"ua": "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
     "vp": (384, 854), "device": "Galaxy S24 Ultra"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
     "vp": (360, 800), "device": "Galaxy A54"},
    {"ua": "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) "
           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
           "Mobile/15E148 Safari/604.1",
     "vp": (820, 1180), "device": "iPad Air"},
    {"ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
     "vp": (1920, 1080), "device": "Desktop · Linux/Chrome"},
]

# ─── Free Proxy Sources ─────────────────────────────────────────
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies"
    "&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite",
    "https://api.proxyscrape.com/v2/?request=displayproxies"
    "&protocol=http&timeout=5000&country=all&ssl=all&anonymity=anonymous",
    "https://www.proxy-list.download/api/v1/get?type=https",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Proxy Manager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ProxyManager:
    """Fetches and rotates free HTTP/HTTPS proxies."""

    REFRESH_INTERVAL = 30 * 60  # 30 minutes

    def __init__(self):
        self.proxies: list[str] = []
        self.last_refresh: datetime | None = None
        self._lock = threading.Lock()
        self._log_fn = None

    def set_logger(self, fn):
        self._log_fn = fn

    def _log(self, level, msg):
        if self._log_fn:
            self._log_fn(level, msg)

    def refresh(self):
        new_proxies: list[str] = []
        for source in PROXY_SOURCES:
            try:
                resp = http_requests.get(source, timeout=10)
                if resp.status_code == 200:
                    for line in resp.text.strip().splitlines():
                        p = line.strip()
                        if p and ":" in p:
                            new_proxies.append(p)
            except Exception:
                continue

        with self._lock:
            self.proxies = list(set(new_proxies))
            random.shuffle(self.proxies)
            self.last_refresh = datetime.now()

        self._log("info", f"Proxy pool refreshed — {len(self.proxies)} proxies")

    def get_proxy(self) -> str | None:
        with self._lock:
            return random.choice(self.proxies) if self.proxies else None

    def remove_proxy(self, proxy: str):
        with self._lock:
            try:
                self.proxies.remove(proxy)
            except ValueError:
                pass

    @property
    def count(self) -> int:
        with self._lock:
            return len(self.proxies)

    def needs_refresh(self) -> bool:
        if not self.last_refresh:
            return True
        return (datetime.now() - self.last_refresh).total_seconds() > self.REFRESH_INTERVAL


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Bot Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BotEngine:
    """Background worker that visits a URL with a real headless browser."""

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
        self.log: list[dict] = []
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.proxy_manager = ProxyManager()
        self.proxy_manager.set_logger(self._log)

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

    # ── Chrome Driver Factory ────────────────────────────────────
    @staticmethod
    def _create_driver(profile: dict, proxy: str | None = None):
        """Launch a headless Chrome with the given fingerprint."""
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-popup-blocking")

        # Memory optimizations (Render free-tier = 512 MB)
        opts.add_argument("--single-process")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--disable-backgrounding-occluded-windows")
        opts.add_argument("--js-flags=--max-old-space-size=128")

        # Random fingerprint
        opts.add_argument(f"--user-agent={profile['ua']}")
        w, h = profile["vp"]
        opts.add_argument(f"--window-size={w},{h}")

        # Proxy
        if proxy:
            opts.add_argument(f"--proxy-server=http://{proxy}")

        # Chrome binary (auto-detected at boot)
        if CHROME_BINARY:
            opts.binary_location = CHROME_BINARY

        # ChromeDriver (system → webdriver-manager fallback)
        svc = _get_chromedriver_service()
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.set_page_load_timeout(30)
        return driver

    # ── Realistic Scroll Behaviour ───────────────────────────────
    @staticmethod
    def _scroll_page(driver, duration_target: float = 10.0):
        """Scroll down the page gradually over ~duration_target seconds."""
        try:
            total_h = driver.execute_script(
                "return Math.max("
                "  document.body.scrollHeight,"
                "  document.documentElement.scrollHeight"
                ")"
            )
        except Exception:
            total_h = 4000

        steps = random.randint(5, 8)
        per_step = duration_target / steps

        for i in range(1, steps + 1):
            target_y = int(total_h * i / steps)
            driver.execute_script(
                f"window.scrollTo({{top:{target_y},behavior:'smooth'}})"
            )
            time.sleep(per_step + random.uniform(-0.3, 0.5))

        # Pause at bottom (like reading)
        time.sleep(random.uniform(1.0, 3.0))

    # ── Single Visit ─────────────────────────────────────────────
    def _visit(self):
        profile = random.choice(DEVICE_PROFILES)
        device = profile["device"]

        # Refresh proxy pool when stale
        if self.proxy_manager.needs_refresh():
            try:
                self.proxy_manager.refresh()
            except Exception:
                self._log("info", "Proxy refresh failed — will use direct")

        # Try up to 3 proxies, then fall back to direct connection
        MAX_PROXY_TRIES = 3
        for attempt in range(MAX_PROXY_TRIES + 1):
            proxy = (
                self.proxy_manager.get_proxy()
                if attempt < MAX_PROXY_TRIES
                else None
            )

            driver = None
            try:
                driver = self._create_driver(profile, proxy=proxy)
                driver.get(self.url)

                # Wait for page load
                time.sleep(random.uniform(2.5, 4.5))

                # Scroll for ~10 seconds
                self._scroll_page(driver)

                # ── Success ──────────────────────────────────────
                with self._lock:
                    self.visit_count += 1
                    self.success_count += 1
                    self.last_visit = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                via = f"proxy {proxy}" if proxy else "direct"
                self._log(
                    "success",
                    f"Visit #{self.visit_count} — {device} ({via})",
                )
                return  # done

            except WebDriverException as exc:
                short = str(exc)[:80]
                if proxy:
                    self.proxy_manager.remove_proxy(proxy)
                    self._log("info", f"Proxy failed ({short}), trying next…")
                    continue
                with self._lock:
                    self.visit_count += 1
                    self.fail_count += 1
                self._log("error", f"Visit failed — {short}")
                return

            except Exception as exc:
                if proxy:
                    self.proxy_manager.remove_proxy(proxy)
                    continue
                with self._lock:
                    self.visit_count += 1
                    self.fail_count += 1
                self._log("error", f"Visit failed — {str(exc)[:80]}")
                return

            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass

        # Exhausted all attempts
        with self._lock:
            self.visit_count += 1
            self.fail_count += 1
        self._log("error", "All proxy attempts failed")

    # ── Main Loop ────────────────────────────────────────────────
    def _loop(self):
        self._log("info", "Bot started — fetching proxies…")
        try:
            self.proxy_manager.refresh()
        except Exception:
            self._log("info", "Initial proxy fetch failed — will retry")

        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(1)
                continue

            self._visit()

            # Interval with ±60 s jitter (min 60 s)
            jitter = random.randint(-60, 60)
            wait = max(60, self.interval * 60 + jitter)

            with self._lock:
                self.next_visit = (
                    datetime.now() + timedelta(seconds=wait)
                ).strftime("%Y-%m-%d %H:%M:%S")

            for _ in range(wait):
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
        return {
            "ok": True,
            "msg": f"Updated: {', '.join(changes)}" if changes else "No changes",
        }

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
                "proxyPool": self.proxy_manager.count,
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
        return
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
        session.permanent = True  # honour permanent_session_lifetime
        session["auth"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Wrong PIN"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
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