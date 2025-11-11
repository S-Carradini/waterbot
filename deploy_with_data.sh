#!/bin/bash
set -e

echo "🚀 Building Docker image with pre-built ChromaDB vector database..."

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

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
elif [ -f "application/.env" ]; then
    echo "📄 Loading environment variables from application/.env file..."
    export $(grep -v '^#' application/.env | xargs)
fi

# Login to ACR
echo "📦 Logging into Azure Container Registry..."
az acr login --name waterbotregistry

# OpenAI API key is optional now (only needed if rebuilding index inside container)
# But we'll still pass it as an environment variable for runtime use
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set. It will not be available in the container."
    echo "   Set it in .env file or with: export OPENAI_API_KEY='your-key'"
    BUILD_ARGS=""
else
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
    echo "✅ OPENAI_API_KEY will be available in container (for runtime use)"
fi

# Build the image for linux/amd64 platform (required for Azure Container Apps)
echo "🔨 Building image for linux/amd64 platform..."
echo "   Using pre-built ChromaDB from application/docs/chroma"
docker build --platform linux/amd64 $BUILD_ARGS -t waterbotregistry.azurecr.io/waterbot-backend:newdata .

# Push the image
echo "⬆️  Pushing image to registry..."
docker push waterbotregistry.azurecr.io/waterbot-backend:newdata

# Update the container app
echo "🔄 Updating container app..."
az containerapp update \
  --resource-group waterbot-test-rg \
  --name waterbot-backend \
  --image waterbotregistry.azurecr.io/waterbot-backend:newdata

echo "✅ Deployment complete!"
echo ""
echo "📝 The pre-built ChromaDB vector database has been included in the Docker image."
echo "   The vector store is ready to use immediately after deployment."
echo ""
echo "💡 To rebuild the vector database with new documents:"
echo "   1. Run locally: python application/scripts/Add_files_to_db.py"
echo "   2. Re-run this script to rebuild and deploy the image"

