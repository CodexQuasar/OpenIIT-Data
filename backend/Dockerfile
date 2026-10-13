# Backend Dockerfile
FROM python:3.11-slim

WORKDIR /app/backend

# Install system dependencies (libgomp1 is required by lightgbm at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application and repository-level runtime data
COPY backend/ .
COPY Dataset/ /app/Dataset/
COPY evaluation_artifacts/ /app/evaluation_artifacts/

# Create data directory
RUN mkdir -p data models

# Expose port
EXPOSE 8000

# Run application
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]