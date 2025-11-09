#!/bin/bash
set -e

echo "🚀 Building Docker image with newData folder for Docker Hub..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop or Colima."
    echo "   For Colima: colima start"
    exit 1
fi

# Get Docker Hub username
if [ -z "$DOCKER_HUB_USERNAME" ]; then
    echo "📝 Enter your Docker Hub username:"
    read DOCKER_HUB_USERNAME
fi

# Get OpenAI API key from environment or prompt
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set. RAG loading will be skipped during build."
    echo "   Set it with: export OPENAI_API_KEY='your-key'"
    BUILD_ARGS=""
else
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
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

echo "✅ Build and push complete!"
echo ""
echo "📝 Image available at: docker.io/${IMAGE_NAME}:${TAG}"
echo ""
echo "💡 To use this image:"
echo "   docker pull ${IMAGE_NAME}:${TAG}"
echo ""
echo "📝 The RAG vector store has been built into the image during the Docker build process."
echo "   If RAG loading was skipped, you can still run it manually:"
echo "   docker run -it ${IMAGE_NAME}:${TAG} python scripts/Add_files_to_db.py"

