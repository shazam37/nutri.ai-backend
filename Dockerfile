# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install system dependencies needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────
# Runtime stage — lean final image
# ─────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# libpq-dev runtime portion is needed by asyncpg/psycopg2
# curl is needed for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Environment
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code
# .dockerignore will exclude .env, __pycache__, .venv, tests/ etc.
COPY . .

# Render injects PORT automatically — default to 8000 for local docker runs
EXPOSE 8000

# Health check — Render also uses this to confirm the container is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start server — reads $PORT from Render's environment
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]