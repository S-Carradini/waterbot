#!/bin/bash
# Build script that captures and shows RAG loader output

cd "$(dirname "$0")"

# Load .env
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "🔨 Building Docker image..."
echo "📝 Build output will be saved to docker_build.log"
echo "🔍 Watching for RAG loader output..."
echo ""

# Build and capture output
docker build --platform linux/amd64 \
    --build-arg OPENAI_API_KEY="$OPENAI_API_KEY" \
    -t shankerram3/waterbot-backend:latest . 2>&1 | \
    tee docker_build.log | \
    grep --line-buffered -E "Checking RAG|RAG loader|Starting RAG|OPENAI_API_KEY|newData|PDF count|Loading documents|Adding :|Successfully added|Failed|Error|❌|✅|📄|🚀" || \
    cat docker_build.log | tail -100

echo ""
echo "📋 Full build log saved to: docker_build.log"
echo "🔍 To see RAG loader section: grep -A 50 'Checking RAG' docker_build.log"

