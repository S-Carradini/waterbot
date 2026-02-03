#!/bin/bash
set -e

echo "🚀 Building Docker image and pushing to Docker Hub..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop or Colima."
    echo "   For Colima: colima start"
    exit 1
fi

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
elif [ -f "application/.env" ]; then
    echo "📄 Loading environment variables from application/.env file..."
    export $(grep -v '^#' application/.env | xargs)
else
    echo "⚠️  No .env file found. Using environment variables from shell."
fi

# RAG vector store is PostgreSQL (pgvector). Set DB_* at runtime for RAG.
echo "✅ Frontend will be built inside Docker (OS-agnostic)"

# Get Docker Hub username
if [ -z "$DOCKER_HUB_USERNAME" ]; then
    echo "📝 Enter your Docker Hub username:"
    read DOCKER_HUB_USERNAME
fi

# Build arguments (optional - only if OPENAI_API_KEY is set)
    BUILD_ARGS=""
if [ -n "$OPENAI_API_KEY" ]; then
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
    echo "✅ OPENAI_API_KEY will be available in container"
fi

# Image name and tag
IMAGE_NAME="${DOCKER_HUB_USERNAME}/waterbot-backend"
TAG="${1:-latest}"

# Build the image for linux/amd64 platform (required for most cloud platforms)
echo "🔨 Building Docker image for linux/amd64 platform..."
echo "   RAG uses PostgreSQL (pgvector); set DB_* in container."
echo "   Building frontend inside Docker (OS-agnostic)"
docker build --platform linux/amd64 $BUILD_ARGS -t "${IMAGE_NAME}:${TAG}" .

# Login to Docker Hub
echo "📦 Logging into Docker Hub..."
docker login -u "$DOCKER_HUB_USERNAME"

# Push the image
echo "⬆️  Pushing image to Docker Hub..."
docker push "${IMAGE_NAME}:${TAG}"

# Optionally push to Azure Container Registry as well
if command -v az &> /dev/null && az account show &> /dev/null 2>&1; then
    echo ""
    echo "📦 Also pushing to Azure Container Registry..."
    ACR_NAME="${ACR_NAME:-waterbotregistry}"
    echo "Logging into Azure Container Registry..."
    
    if az acr login --name "$ACR_NAME" 2>/dev/null; then
        # Tag for ACR
        ACR_IMAGE="${ACR_NAME}.azurecr.io/waterbot-backend:${TAG}"
        docker tag "${IMAGE_NAME}:${TAG}" "$ACR_IMAGE"
        
        echo "Pushing to Azure Container Registry..."
        docker push "$ACR_IMAGE"
        
        echo "✅ Also pushed to: $ACR_IMAGE"
        export ACR_IMAGE_PUSHED="$ACR_IMAGE"
    else
        echo "⚠️  Could not login to ACR, skipping Azure push"
    fi
fi

echo ""
echo "✅ Build and push complete!"
echo ""
echo "📝 Image available at:"
echo "   Docker Hub: docker.io/${IMAGE_NAME}:${TAG}"
if [ -n "$ACR_IMAGE_PUSHED" ]; then
    echo "   Azure ACR: $ACR_IMAGE_PUSHED"
fi
echo ""
echo "💡 To use this image:"
echo "   docker pull ${IMAGE_NAME}:${TAG}"
echo "   docker run -p 8000:8000 ${IMAGE_NAME}:${TAG}"
echo ""
echo "📝 The frontend was built inside Docker. RAG uses PostgreSQL (pgvector); set DB_* in container."

