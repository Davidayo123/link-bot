FROM python:3.11-slim

# ── Install Chromium + ChromeDriver + system fonts ──────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
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
        xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Environment ─────────────────────────────────────────────────
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

# ── Python deps (cached layer) ──────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ────────────────────────────────────────────
COPY . .

EXPOSE 10000

CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT:-10000} --timeout 120 --workers 1"]
