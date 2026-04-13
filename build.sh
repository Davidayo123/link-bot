#!/usr/bin/env bash
set -o errexit

echo "=== Installing system dependencies (Chrome + ChromeDriver) ==="
apt-get update -y
apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Verifying Chrome installation ==="
which chromium && chromium --version || echo "chromium not in PATH"
which chromedriver && chromedriver --version || echo "chromedriver not in PATH"
echo "=== Build complete ==="
