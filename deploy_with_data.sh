#!/bin/bash
set -e

echo "🚀 Building Docker image with newData folder included..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop or Colima."
    echo "   For Colima: colima start"
    exit 1
fi

# Login to ACR
echo "📦 Logging into Azure Container Registry..."
az acr login --name waterbotregistry

# Get OpenAI API key from environment or prompt
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set. RAG loading will be skipped during build."
    echo "   Set it with: export OPENAI_API_KEY='your-key'"
    BUILD_ARGS=""
else
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
fi

# Build the image for linux/amd64 platform (required for Azure Container Apps)
# Using --no-cache to ensure newData folder is included after .dockerignore fix
echo "🔨 Building image for linux/amd64 platform (no cache)..."
docker build --platform linux/amd64 --no-cache $BUILD_ARGS -t waterbotregistry.azurecr.io/waterbot-backend:newdata .

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
echo "📝 The RAG vector store has been built into the image during the Docker build process."
echo "   If RAG loading was skipped, you can still run it manually:"
echo "   1. Connect: az containerapp exec --resource-group waterbot-test-rg --name waterbot-backend --command /bin/bash"
echo "   2. Inside container, run: python scripts/Add_files_to_db.py"

