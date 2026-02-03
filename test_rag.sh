#!/bin/bash

# Test script for WaterBot RAG functionality
# Usage: ./test_rag.sh [your-container-app-url]

CONTAINER_URL="${1:-waterbot-backend.whiterock-47461ff8.uksouth.azurecontainerapps.io}"
BASE_URL="https://${CONTAINER_URL}"
COOKIE_FILE="/tmp/waterbot_session_cookie.txt"

echo "🧪 Testing WaterBot RAG Functionality"
echo "======================================"
echo "Container URL: $BASE_URL"
echo ""

# Test 1: Simple water-related question
echo "📝 Test 1: Asking about Arizona water supply..."
RESPONSE=$(curl -X POST "${BASE_URL}/chat_api" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_query=What is the status of Arizona's water supply?" \
  -c "$COOKIE_FILE" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS/d')

echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
echo ""

# Check if response mentions specific Arizona water concepts (indicating RAG is working)
if echo "$BODY" | grep -qiE "(Active Management Area|AMA|Colorado River|groundwater|CAGRD|water banking)"; then
    echo "✅ RAG appears to be working - response mentions specific Arizona water concepts"
else
    echo "⚠️  Response may not be using RAG - check if documents were loaded"
fi

echo ""
echo ""

# Test 2: Get sources for the previous query
if [ -f "$COOKIE_FILE" ]; then
    echo "📚 Test 2: Retrieving sources for the previous query..."
    SOURCES=$(curl -X POST "${BASE_URL}/chat_sources_api" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      -b "$COOKIE_FILE" \
      -s)
    
    echo "$SOURCES" | jq -r '.resp' 2>/dev/null || echo "$SOURCES"
    
    if echo "$SOURCES" | grep -qiE "\.pdf|source|document"; then
        echo "✅ Sources retrieved successfully"
    else
        echo "⚠️  No sources found - RAG may not be working correctly"
    fi
    echo ""
fi

# Test 3: Question about Colorado River
echo "📝 Test 3: Asking about Colorado River shortage..."
curl -X POST "${BASE_URL}/chat_api" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_query=What is the Colorado River shortage situation?" \
  -b "$COOKIE_FILE" \
  -s | jq '.' 2>/dev/null || cat

echo ""
echo ""

# Cleanup
rm -f "$COOKIE_FILE"

echo "✅ Testing complete!"
echo ""
echo "💡 To verify RAG is working correctly:"
echo "   1. Check container logs: az containerapp logs show --resource-group waterbot-test-rg --name waterbot-backend --follow"
echo "   2. Look for 'Adding : newData/...' messages indicating document processing"
echo "   3. Check if RAG has data: ensure DATABASE_URL or DB_* env and pgvector rag_chunks table are populated"
echo ""
echo "🔍 Signs RAG is working:"
echo "   ✅ Responses mention specific documents, reports, or studies"
echo "   ✅ Answers include specific facts, numbers, or policy details"
echo "   ✅ Sources endpoint returns PDF filenames"
echo "   ❌ Generic water information without citations = RAG not working"

