# Dockerfile — OrçaTech

FROM python:3.12-slim

# Chrome + Xvfb (display virtual) + libs que o Chrome precisa pra rodar
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip xvfb \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libnspr4 libnss3 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    xdg-utils \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5000
EXPOSE 5000

# xvfb-run cria o display virtual (":99") automaticamente e roda o app
# dentro dele — o Chrome não-headless funciona normal, sem precisar de
# monitor de verdade.
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "app.py"]
