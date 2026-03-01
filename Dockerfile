FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (no secrets -- they come from env vars)
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Run both the scheduler and the Telegram poller
# Using a simple entrypoint script
CMD ["python", "entrypoint.py"]
