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
        echo "⚠️  Running with sudo - will run Python as original user to preserve venv"
        
        # Change to script directory
        cd "$SCRIPT_DIR"
        
        # Try to detect venv - check multiple locations
        PYTHON_CMD=""
        
        # First, check VIRTUAL_ENV variable (set when venv is activated)
        if [ -n "$VIRTUAL_ENV" ] && [ -f "$VIRTUAL_ENV/bin/python" ]; then
            PYTHON_CMD="$VIRTUAL_ENV/bin/python"
            echo "✅ Found activated venv: $VIRTUAL_ENV"
        # Check current working directory (PWD is preserved by sudo)
        elif [ -f "$PWD/.venv/bin/python" ]; then
            PYTHON_CMD="$PWD/.venv/bin/python"
            echo "✅ Found venv at $PWD/.venv"
        elif [ -f "$PWD/venv/bin/python" ]; then
            PYTHON_CMD="$PWD/venv/bin/python"
            echo "✅ Found venv at $PWD/venv"
        # Check script directory
        elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
            echo "✅ Found venv at $SCRIPT_DIR/.venv"
        elif [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
            PYTHON_CMD="$SCRIPT_DIR/venv/bin/python"
            echo "✅ Found venv at $SCRIPT_DIR/venv"
        # Check original user's home directory (from error message path)
        elif [ -f "$ORIGINAL_HOME/applications/waterbot/waterbot/.venv/bin/python" ]; then
            PYTHON_CMD="$ORIGINAL_HOME/applications/waterbot/waterbot/.venv/bin/python"
            echo "✅ Found venv at $ORIGINAL_HOME/applications/waterbot/waterbot/.venv"
        elif [ -f "$ORIGINAL_HOME/applications/waterbot/waterbot/venv/bin/python" ]; then
            PYTHON_CMD="$ORIGINAL_HOME/applications/waterbot/waterbot/venv/bin/python"
            echo "✅ Found venv at $ORIGINAL_HOME/applications/waterbot/waterbot/venv"
        fi
        
        if [ -n "$PYTHON_CMD" ]; then
            # Use the found venv Python, running as original user
            echo "🐍 Using Python: $PYTHON_CMD"
            sudo -u "$ORIGINAL_USER" "$PYTHON_CMD" application/scripts/Add_files_to_db.py
        else
            # Fallback: try with original user's PATH (may include venv)
            echo "⚠️  Venv not found in common locations, trying with original user's environment..."
            sudo -u "$ORIGINAL_USER" -E env "PATH=$PATH" python3 application/scripts/Add_files_to_db.py || {
                echo ""
                echo "❌ Could not find virtual environment or run Python script."
                echo "   Options:"
                echo "   1. Run without sudo (recommended):"
                echo "      sudo usermod -aG docker $ORIGINAL_USER"
                echo "      # Then logout/login and run: ./docker_build.sh"
                echo "   2. Or install dependencies in system Python:"
                echo "      sudo pip3 install python-dotenv langchain-community langchain-chroma langchain-text-splitters langchain-openai"
                exit 1
            }
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
        
        echo "🐍 Using Python: $PYTHON_CMD"
        
        # Change to script directory to ensure relative paths work
        cd "$SCRIPT_DIR"
        
        $PYTHON_CMD application/scripts/Add_files_to_db.py
    fi
    
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