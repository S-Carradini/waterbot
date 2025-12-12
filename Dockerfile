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
    pip install --no-cache-dir -r requirements.txt

# Copy the application code (needed for the build script)
COPY application/ /app/

# Copy the newData directory with PDF files to build ChromaDB
# This will be used to build the vector database during Docker build
# Note: newData directory must exist in the build context (application/newData)
# If it doesn't exist, the build will fail - ensure PDF/TXT files are in application/newData/
COPY application/newData /app/newData

# Build argument for OpenAI API key (required for building ChromaDB)
ARG OPENAI_API_KEY
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Create docs directory for ChromaDB output
RUN mkdir -p /app/docs/chroma

# Build ChromaDB from files in newData directory
RUN if [ -n "$OPENAI_API_KEY" ] && [ -d "/app/newData" ] && [ "$(find /app/newData -name '*.pdf' -o -name '*.txt' 2>/dev/null | wc -l)" -gt 0 ]; then \
        echo "🚀 Building ChromaDB index from newData files..." && \
        python scripts/Add_files_to_db.py && \
        echo "✅ ChromaDB built successfully"; \
    elif [ -d "/app/newData" ] && [ "$(find /app/newData -name '*.pdf' -o -name '*.txt' 2>/dev/null | wc -l)" -gt 0 ]; then \
        echo "⚠️  OPENAI_API_KEY not set. Skipping ChromaDB build." && \
        echo "   Set OPENAI_API_KEY as build arg: docker build --build-arg OPENAI_API_KEY=your-key ."; \
    elif [ -d "/app/docs/chroma" ] && [ "$(ls -A /app/docs/chroma 2>/dev/null)" ]; then \
        echo "✅ Using existing ChromaDB from docs/chroma"; \
    else \
        echo "⚠️  No newData files found and no existing ChromaDB. ChromaDB will be empty." && \
        echo "   Make sure to copy PDF/TXT files to application/newData before building."; \
    fi

# Set permissions for the chroma directory
RUN chmod -R 755 /app/docs/chroma || true

# Copy the built React frontend from the frontend-builder stage
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Verify ChromaDB status
RUN echo "📊 ChromaDB status:" && \
    ls -la docs/chroma/ 2>/dev/null | head -5 || echo "⚠️  ChromaDB directory is empty"

# Expose the application's port
EXPOSE 8000

# Command to run the application
# Use PORT environment variable if set (for Render/Heroku), otherwise default to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
