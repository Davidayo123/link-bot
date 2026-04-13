FROM python:3.11-slim-bookworm

# ── 1. System deps for headless Chrome ──────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget \
        gnupg2 \
        ca-certificates \
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

# ── 2. Install Google Chrome Stable (most reliable for Selenium) ─
RUN wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── 3. Verify Chrome is installed ───────────────────────────────
RUN google-chrome --version

WORKDIR /app

# ── 4. Python dependencies (cached layer) ──────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 5. Pre-cache matching ChromeDriver via webdriver-manager ────
#    This downloads the correct chromedriver during build so
#    we don't need internet access at runtime.
RUN python -c "\
from webdriver_manager.chrome import ChromeDriverManager; \
path = ChromeDriverManager().install(); \
print(f'ChromeDriver cached at: {path}')"

# ── 6. Application code ────────────────────────────────────────
COPY . .

EXPOSE 10000

CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT:-10000} --timeout 120 --workers 1"]
