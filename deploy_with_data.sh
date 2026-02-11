#!/bin/bash
set -e

echo "🚀 Building Docker image..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop or Colima."
    echo "   For Colima: colima start"
    exit 1
fi

# RAG vector store is PostgreSQL (pgvector). Set DB_* at runtime.
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
echo "📝 RAG uses PostgreSQL (pgvector). Set DATABASE_URL or DB_* and run migration or ingestion after deployment."
echo ""
echo "💡 To rebuild the vector database with new documents:"
echo "   1. Run locally: python application/scripts/Add_files_to_db.py"
echo "   2. Re-run this script to rebuild and deploy the image"

