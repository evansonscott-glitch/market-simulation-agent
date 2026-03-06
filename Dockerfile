FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create output directories
RUN mkdir -p /app/output/runs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default interface: slack
# Override with INTERFACE=web or INTERFACE=cli
ENV INTERFACE=slack

# Expose web port (only used when INTERFACE=web)
EXPOSE 8080

# Entrypoint script to select interface
CMD ["sh", "-c", "\
    if [ \"$INTERFACE\" = 'web' ]; then \
        python web/server.py; \
    elif [ \"$INTERFACE\" = 'cli' ]; then \
        python cli/interactive.py; \
    else \
        python slack_bot/app.py; \
    fi"]
