# Use the official lightweight Python image as a base
FROM python:3.11-slim as app

# Install necessary packages and clean up to reduce image size
# PyPDFLoader requires poppler-utils for PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy only requirements files first to optimize layer caching
COPY /application/requirements.txt /app/
COPY /application/requirements_full.txt /app/

# Install dependencies, using no-cache to avoid cache bloating
# Install requirements_full.txt first (base dependencies), then requirements.txt (which may override versions)
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements_full.txt && \
    pip install --no-cache-dir -r requirements.txt

# Copy the pre-built ChromaDB vector database early for better caching
# This avoids rebuilding the index on every Docker build
# Make sure to run 'python scripts/Add_files_to_db.py' locally first to build the index
COPY /application/docs/chroma /app/docs/chroma

# Set permissions for the chroma directory
RUN chmod -R 755 /app/docs/chroma || true

# Copy the rest of the application code last to avoid invalidating cache during code changes
COPY /application/ /app/

# Copy the React frontend dist directory
COPY /frontend/dist /app/frontend/dist

# Build argument for OpenAI API key (optional, only needed if rebuilding index)
ARG OPENAI_API_KEY
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Skip RAG indexing during build - use pre-built vector database instead
# To rebuild the index, uncomment the section below or run manually:
# RUN if [ -n "$OPENAI_API_KEY" ] && [ -d "newData" ] && [ "$(find newData -name '*.pdf' 2>/dev/null | wc -l)" -gt 0 ]; then \
#         echo "🚀 Rebuilding ChromaDB index..." && \
#         python scripts/Add_files_to_db.py; \
#     else \
#         echo "✅ Using pre-built ChromaDB from COPY command above"; \
#     fi

RUN echo "✅ Using pre-built ChromaDB vector database" && \
    echo "📊 ChromaDB status:" && \
    ls -la docs/chroma/ 2>/dev/null | head -5 || echo "⚠️  ChromaDB directory not found - you may need to rebuild the index"

# Expose the application's port
EXPOSE 8000

# Command to run the application
# Use PORT environment variable if set (for Render/Heroku), otherwise default to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
