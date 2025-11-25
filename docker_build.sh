#!/bin/bash
set -e

echo "🚀 Building Docker image locally..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop or Colima."
    echo "   For Colima: colima start"
    exit 1
fi

# Check if ChromaDB directory exists
if [ ! -d "application/docs/chroma" ]; then
    echo "⚠️  ChromaDB directory not found at application/docs/chroma"
    echo "   Building the vector database first..."
    
    # Load environment variables for building the index
    if [ -f ".env" ]; then
        echo "📄 Loading environment variables from .env file..."
        export $(grep -v '^#' .env | xargs)
    elif [ -f "application/.env" ]; then
        echo "📄 Loading environment variables from application/.env file..."
        export $(grep -v '^#' application/.env | xargs)
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        echo "❌ OPENAI_API_KEY not set. Cannot build ChromaDB index."
        echo "   Set it in .env file or with: export OPENAI_API_KEY='your-key'"
        exit 1
    fi
    
    echo "🔨 Building ChromaDB index..."
    # Use virtual environment Python if it exists, otherwise use system Python
    if [ -f ".venv/bin/python" ]; then
        PYTHON_CMD=".venv/bin/python"
    elif [ -f "application/.venv/bin/python" ]; then
        PYTHON_CMD="application/.venv/bin/python"
    else
        PYTHON_CMD="python3"
    fi
    
    $PYTHON_CMD application/scripts/Add_files_to_db.py
    
    if [ ! -d "application/docs/chroma" ]; then
        echo "❌ Failed to build ChromaDB. Please check the error messages above."
        exit 1
    fi
    
    echo "✅ ChromaDB index built successfully"
else
    echo "✅ Found pre-built ChromaDB at application/docs/chroma"
    echo "   Using existing vector database (no rebuild needed)"
fi

echo "✅ Frontend will be built inside Docker (OS-agnostic)"

# Load environment variables from .env file if it exists (for OPENAI_API_KEY in container)
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
elif [ -f "application/.env" ]; then
    echo "📄 Loading environment variables from application/.env file..."
    export $(grep -v '^#' application/.env | xargs)
fi

# Build arguments (optional - only if OPENAI_API_KEY is set)
BUILD_ARGS=""
if [ -n "$OPENAI_API_KEY" ]; then
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
    echo "✅ OPENAI_API_KEY will be available in container"
fi

# Build the image
# Allow platform override via PLATFORM env var, default to linux/amd64 for consistency
PLATFORM="${PLATFORM:-linux/amd64}"
echo "🔨 Building Docker image for ${PLATFORM} platform..."
echo "   Using pre-built ChromaDB from application/docs/chroma"
echo "   Building frontend inside Docker (OS-agnostic)"
docker build --platform ${PLATFORM} $BUILD_ARGS -t waterbot .

echo ""
echo "✅ Build complete!"
echo ""
echo "📦 Image built: waterbot"
echo ""
echo "🚀 To run the container:"
echo "   docker run -p 8000:8000 waterbot"
echo ""
echo "💡 To rebuild components:"
echo "   - Vector database: python application/scripts/Add_files_to_db.py"
echo "   - Frontend is built automatically inside Docker (no manual build needed)"
echo "   Then re-run this script"