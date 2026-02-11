# Stage 1: Build the React frontend
FROM node:18-alpine AS frontend-builder

WORKDIR /build

# Copy package files
COPY frontend/package.json frontend/package-lock.json* ./

# Install all dependencies (including devDependencies needed for build)
RUN npm ci || npm install

# Copy frontend source code
COPY frontend/ ./

# Build the frontend
RUN npm run build

# Stage 2: Python application
FROM python:3.11-slim AS app

# Install necessary packages and clean up to reduce image size
# PyPDFLoader requires poppler-utils for PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy only requirements files first to optimize layer caching
COPY application/requirements.txt /app/
COPY application/requirements_full.txt /app/

# Install dependencies, using no-cache to avoid cache bloating
# Install requirements_full.txt first (base dependencies), then requirements.txt (which may override versions)
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements_full.txt && \
    pip install --no-cache-dir --no-deps -r requirements.txt

# Copy the application code
COPY application/ /app/

# RAG vector store is PostgreSQL (pgvector). Run migration or ingestion after deploy when DATABASE_URL or DB_* are set.
# Optionally copy newData for runtime ingestion: COPY application/newData /app/newData

# Copy the built React frontend from the frontend-builder stage
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Expose the application's port
EXPOSE 8000

# Command to run the application
# Use PORT environment variable if set (for Render/Heroku), otherwise default to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
