# TradeZen Backend Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build-essential, libpq-dev for PostgreSQL, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and artifacts
COPY . .

EXPOSE 8000

# Start backend (ensuring DB tables and sample data exist)
CMD ["sh", "-c", "python -m scripts.init_db && uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
