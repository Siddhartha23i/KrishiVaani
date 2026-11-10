# ==============================================================================
# KrishiVaani - Railway Production Dockerfile
# Base: Python 3.11 Slim with system FFmpeg for OGG Opus / WAV audio conversion
# Start Command: python -m app.telegram.run
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing bytecode and enable unbuffered output for real-time logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system dependencies:
# - ffmpeg: required for convert_ogg_opus_to_wav and convert_wav_to_ogg_opus
# - curl: utility for health/diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency specifications first for Docker layer caching
COPY requirements.txt /app/

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and verified seed knowledge
COPY app /app/app
COPY data_seed /app/data_seed

# Copy startup entrypoint script and make it executable
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Ensure persistent data directory mount point exists
RUN mkdir -p /app/data

# Entrypoint initializes volume data from seed if missing, then executes command
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default start command: Telegram bot long polling runner
CMD ["python", "-m", "app.telegram.run"]

