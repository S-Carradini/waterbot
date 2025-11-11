#!/bin/bash
set -e

echo "🚀 Building Docker image with newData folder for Docker Hub..."

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

# Get Docker Hub username
if [ -z "$DOCKER_HUB_USERNAME" ]; then
    echo "📝 Enter your Docker Hub username:"
    read DOCKER_HUB_USERNAME
fi

# Get OpenAI API key from environment or prompt
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set. RAG loading will be skipped during build."
    echo "   Set it in .env file or with: export OPENAI_API_KEY='your-key'"
    BUILD_ARGS=""
else
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
    echo "✅ Using OPENAI_API_KEY from environment"
fi

# Image name and tag
IMAGE_NAME="${DOCKER_HUB_USERNAME}/waterbot-backend"
TAG="${1:-latest}"

# Build the image for linux/amd64 platform (required for most cloud platforms)
echo "🔨 Building image for linux/amd64 platform..."
docker build --platform linux/amd64 --no-cache $BUILD_ARGS -t "${IMAGE_NAME}:${TAG}" .

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
echo ""
echo "📝 The RAG vector store has been built into the image during the Docker build process."
echo "   If RAG loading was skipped, you can still run it manually:"
echo "   docker run -it ${IMAGE_NAME}:${TAG} python scripts/Add_files_to_db.py"

