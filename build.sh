#!/usr/bin/env bash
set -o errexit

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Downloading Chrome for Testing (standalone, no apt needed) ==="
python3 << 'PYEOF'
import urllib.request, zipfile, io, json, os, stat, sys

API_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"

try:
    print("Fetching latest stable Chrome version...")
    data = json.loads(urllib.request.urlopen(API_URL, timeout=30).read())
    stable = data["channels"]["Stable"]
    version = stable["version"]
    print(f"Chrome for Testing v{version}")

    # Download Chrome binary
    for item in stable["downloads"]["chrome"]:
        if item["platform"] == "linux64":
            print(f"Downloading Chrome from {item['url']}...")
            resp = urllib.request.urlopen(item["url"], timeout=120)
            with zipfile.ZipFile(io.BytesIO(resp.read())) as z:
                z.extractall(".")
            os.chmod("chrome-linux64/chrome", os.stat("chrome-linux64/chrome").st_mode | stat.S_IEXEC)
            print("Chrome binary ready at chrome-linux64/chrome")
            break

    # Download matching ChromeDriver
    for item in stable["downloads"]["chromedriver"]:
        if item["platform"] == "linux64":
            print(f"Downloading ChromeDriver from {item['url']}...")
            resp = urllib.request.urlopen(item["url"], timeout=120)
            with zipfile.ZipFile(io.BytesIO(resp.read())) as z:
                z.extractall(".")
            os.chmod("chromedriver-linux64/chromedriver", os.stat("chromedriver-linux64/chromedriver").st_mode | stat.S_IEXEC)
            print("ChromeDriver ready at chromedriver-linux64/chromedriver")
            break

    # Quick version check
    os.system("./chrome-linux64/chrome --version --headless --no-sandbox 2>/dev/null || echo 'Note: Chrome version check skipped'")
    os.system("./chromedriver-linux64/chromedriver --version 2>/dev/null || echo 'Note: ChromeDriver version check skipped'")

except Exception as e:
    print(f"WARNING: Chrome download failed ({e}). Bot will use HTTP mode.")
    sys.exit(0)
PYEOF

echo "=== Build complete ==="
