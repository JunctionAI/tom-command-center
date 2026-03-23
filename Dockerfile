FROM python:3.12-slim

ENV TZ=Pacific/Auckland
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (no secrets -- they come from env vars)
COPY . .

# Create data directory for SQLite (writable at runtime)
RUN mkdir -p /app/data

# Make state init script executable
RUN chmod +x /app/scripts/init_state.sh

# Expose dashboard API port (serves /api/system-health for live monitoring)
EXPOSE 8050

# Secrets come from Railway env vars: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID

# init_state.sh symlinks agent state dirs to the persistent volume before starting
CMD ["/bin/bash", "-c", "/app/scripts/init_state.sh && python entrypoint.py"]
