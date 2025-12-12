#!/bin/bash
set -e

echo "🚀 Building Docker image locally..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running."
    
    # Detect OS and provide appropriate instructions
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "   On Linux, start Docker daemon with:"
        echo "   sudo systemctl start docker"
        echo ""
        echo "   Or if Docker is not installed:"
        echo "   sudo apt-get update && sudo apt-get install -y docker.io"
        echo "   sudo systemctl enable docker"
        echo "   sudo systemctl start docker"
        echo ""
        echo "   Note: You may need to add your user to the docker group:"
        echo "   sudo usermod -aG docker $USER"
        echo "   (Then log out and back in)"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   On macOS, start Docker Desktop or Colima:"
        echo "   For Colima: colima start"
        echo "   For Docker Desktop: Open Docker Desktop application"
    else
        echo "   Please ensure Docker is installed and running."
    fi
    exit 1
fi

# Check if user has permission to run Docker (Linux-specific)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if ! docker ps > /dev/null 2>&1; then
        # If running with sudo, try without sudo first
        if [ -n "$SUDO_USER" ]; then
            echo "⚠️  Running with sudo detected."
            echo "   Note: If you add your user to the docker group, you won't need sudo:"
            echo "   sudo usermod -aG docker $SUDO_USER"
            echo "   (Then log out and back in, and run without sudo)"
            echo ""
        else
            echo "⚠️  Docker is running but you may not have permission."
            echo "   Try: sudo docker ps"
            echo "   Or add your user to the docker group:"
            echo "   sudo usermod -aG docker $USER"
            echo "   (Then log out and back in)"
            exit 1
        fi
    fi
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
    
    # Get the script's directory (works even when run with sudo)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # Detect if running with sudo and get original user's environment
    if [ -n "$SUDO_USER" ]; then
        ORIGINAL_USER="$SUDO_USER"
        ORIGINAL_HOME=$(eval echo ~$SUDO_USER)
        echo "⚠️  Running with sudo - will try to use original user's virtual environment"
        
        # Try to preserve original user's PATH by checking common venv locations
        # First, try to find venv in the current working directory (preserved by sudo -E)
        if [ -f "$PWD/.venv/bin/python" ]; then
            PYTHON_CMD="$PWD/.venv/bin/python"
        elif [ -f "$PWD/venv/bin/python" ]; then
            PYTHON_CMD="$PWD/venv/bin/python"
        # Try script directory
        elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
        elif [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/venv/bin/python"
        # Try original user's home directory (common location from error message)
        elif [ -f "$ORIGINAL_HOME/applications/waterbot/waterbot/.venv/bin/python" ]; then
            PYTHON_CMD="$ORIGINAL_HOME/applications/waterbot/waterbot/.venv/bin/python"
        elif [ -f "$ORIGINAL_HOME/applications/waterbot/waterbot/venv/bin/python" ]; then
            PYTHON_CMD="$ORIGINAL_HOME/applications/waterbot/waterbot/venv/bin/python"
        else
            PYTHON_CMD="python3"
            echo "⚠️  Virtual environment not found. When using sudo, you may need to:"
            echo "   1. Run without sudo (after adding user to docker group):"
            echo "      sudo usermod -aG docker $ORIGINAL_USER"
            echo "      # Then logout/login and run: ./docker_build.sh"
            echo "   2. Or install dependencies in system Python:"
            echo "      sudo pip3 install python-dotenv langchain-community langchain-chroma langchain-text-splitters langchain-openai"
        fi
    else
        # Not running with sudo - normal detection
        if [ -f ".venv/bin/python" ]; then
            PYTHON_CMD=".venv/bin/python"
        elif [ -f "venv/bin/python" ]; then
            PYTHON_CMD="venv/bin/python"
        elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
        elif [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/venv/bin/python"
        else
            PYTHON_CMD="python3"
            echo "⚠️  No virtual environment found, using system Python"
        fi
    fi
    
    echo "🐍 Using Python: $PYTHON_CMD"
    
    # Change to script directory to ensure relative paths work
    cd "$SCRIPT_DIR"
    
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