# Use the official lightweight Python image as a base
FROM python:3.11-slim as app

# Install necessary packages and clean up to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the large 'chroma' folder first to maximize caching
# COPY /application/docs/chroma /app/docs/chroma

# Set permissions for the chroma directory (if necessary)
# RUN chown -R root:root /app/docs/chroma && \
#     chmod -R 755 /app/docs/chroma

# Copy only requirements files first to optimize layer caching
COPY /application/requirements.txt /app/
COPY /application/requirements_full.txt /app/

# Install dependencies, using no-cache to avoid cache bloating
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements_full.txt

# Copy the rest of the application code last to avoid invalidating cache during code changes
COPY /application/ /app/

# Copy the React frontend dist directory
COPY /frontend/dist /app/frontend/dist

# Build argument for OpenAI API key (required for RAG loading)
ARG OPENAI_API_KEY
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Run RAG loader to populate ChromaDB with documents during build
# This ensures the vector store is ready when the container starts
RUN echo "🔍 Checking RAG loader prerequisites..." && \
    echo "OPENAI_API_KEY is $(if [ -n "$OPENAI_API_KEY" ]; then echo 'SET'; else echo 'NOT SET'; fi)" && \
    echo "newData directory exists: $(test -d newData && echo 'YES' || echo 'NO')" && \
    echo "PDF count: $(find newData -name '*.pdf' 2>/dev/null | wc -l)" && \
    if [ -n "$OPENAI_API_KEY" ] && [ -d "newData" ] && [ "$(find newData -name '*.pdf' 2>/dev/null | wc -l)" -gt 0 ]; then \
        echo "🚀 Loading documents into ChromaDB..." && \
        python scripts/Add_files_to_db.py 2>&1 | tee /tmp/rag_loader.log && \
        echo "✅ RAG loading complete. Check /tmp/rag_loader.log for details." && \
        echo "📊 ChromaDB status:" && \
        ls -la docs/chroma/ 2>/dev/null || echo "ChromaDB directory not found"; \
    else \
        echo "⚠️  Skipping RAG loading:" && \
        [ -z "$OPENAI_API_KEY" ] && echo "  - OPENAI_API_KEY not set" || true && \
        [ ! -d "newData" ] && echo "  - newData directory not found" || true && \
        [ "$(find newData -name '*.pdf' 2>/dev/null | wc -l)" -eq 0 ] && echo "  - No PDFs found in newData/" || true && \
        echo "  Run 'python scripts/Add_files_to_db.py' manually after container starts"; \
    fi

# Expose the application's port
EXPOSE 8000

# Command to run the application
# Use PORT environment variable if set (for Render/Heroku), otherwise default to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
