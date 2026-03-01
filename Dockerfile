FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (no secrets -- they come from env vars)
COPY . .

# Create data directory for SQLite (writable at runtime)
RUN mkdir -p /app/data

# No port exposed -- this is a worker (Telegram poller + scheduler)
# Secrets come from Railway env vars: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID

CMD ["python", "entrypoint.py"]
