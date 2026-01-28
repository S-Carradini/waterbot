#!/bin/bash
################################################################################
# Waterbot User Feedback Exporter - DynamoDB
# Retrieves user feedback (reactions and comments) from DynamoDB via API
# Creates both detailed TXT report and CSV file
################################################################################

#RUN: bash ./application/scripts/get_feedback_from_dynamodb.sh

# Get the directory where THIS script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load environment variables from .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "📄 Loading .env from: $SCRIPT_DIR/.env"
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
elif [ -f "$SCRIPT_DIR/../.env" ]; then
    echo "📄 Loading .env from: $SCRIPT_DIR/../.env"
    export $(grep -v '^#' "$SCRIPT_DIR/../.env" | xargs)
elif [ -f "$SCRIPT_DIR/../../.env" ]; then
    echo "📄 Loading .env from: $SCRIPT_DIR/../../.env"
    export $(grep -v '^#' "$SCRIPT_DIR/../../.env" | xargs)
else
    echo "❌ Error: .env file not found in any of these locations:"
    echo "   - $SCRIPT_DIR/.env"
    echo "   - $SCRIPT_DIR/../.env"
    echo "   - $SCRIPT_DIR/../../.env"
    echo ""
    echo "💡 Your .env file should be in the application directory."
    echo "   Expected location: application/.env"
    exit 1
fi

# Configuration (loaded from environment)
PROD_URL="${PROD_URL:-https://azwaterbot.org}"
USERNAME="${API_USERNAME}"
PASSWORD="${API_PASSWORD}"
TXT_OUTPUT="$SCRIPT_DIR/dynamodb_feedback_detailed.txt"
CSV_OUTPUT="$SCRIPT_DIR/dynamodb_feedback.csv"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is not installed"
    echo "   Install it with: brew install jq (Mac) or apt-get install jq (Linux)"
    exit 1
fi

echo "================================================================================================"
echo "                    WATERBOT USER FEEDBACK EXPORTER - DYNAMODB"
echo "================================================================================================"
echo ""
echo "📁 Saving files to: $SCRIPT_DIR"
echo "📊 Fetching feedback from DynamoDB via API..."
echo "🌐 URL: $PROD_URL/feedback"

# Fetch feedback from API
MESSAGES=$(curl -s -u "$USERNAME:$PASSWORD" "$PROD_URL/feedback")

# Check if fetch was successful
if [ -z "$MESSAGES" ] || [ "$MESSAGES" == "null" ]; then
    echo "❌ Error: Could not fetch feedback from API"
    echo "   This might mean:"
    echo "   • Production is not deployed yet"
    echo "   • DynamoDB table not set up"
    echo "   • Network connectivity issue"
    echo "   • Wrong credentials"
    exit 1
fi

# Get total count
TOTAL_COUNT=$(echo "$MESSAGES" | jq 'length')

if [ "$TOTAL_COUNT" == "0" ]; then
    echo "⚠️  No messages found in DynamoDB table"
    echo "   Database is empty - no users have chatted yet"
    exit 0
fi

# Get count of items with feedback (reaction or comment)
FEEDBACK_COUNT=$(echo "$MESSAGES" | jq '[.[] | select(.reaction != null or .userComment != null)] | length')

echo "✅ Found $TOTAL_COUNT total messages"
echo "💬 Found $FEEDBACK_COUNT messages with feedback (reactions or comments)"
echo ""

################################################################################
# CREATE DETAILED TXT REPORT
################################################################################

echo "📄 Creating detailed TXT report..."

{
  echo "================================================================================================"
  echo "                    WATERBOT USER FEEDBACK - DYNAMODB"
  echo "================================================================================================"
  echo ""
  echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Total Messages: $TOTAL_COUNT"
  echo "Messages with Feedback: $FEEDBACK_COUNT"
  echo "Database: DynamoDB"
  echo "URL: $PROD_URL"
  echo ""
  echo "================================================================================================"
  echo ""
  
  # Show only messages with feedback (reaction or comment)
  echo "$MESSAGES" | jq -r '.[] | select(.reaction != null or .userComment != null) | 
  "FEEDBACK ENTRY\n" +
  "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
  "Session UUID:  " + .sessionId + "\n" +
  "Message ID:    " + .msgId + "\n" +
  "Timestamp:     " + .timestamp + "\n" +
  "\n" +
  "👤 USER QUERY:\n" + .userQuery + "\n" +
  "\n" +
  "🤖 BOT RESPONSE:\n" + (.responseContent | gsub("<br><br>"; "\n\n") | gsub("<br>"; "\n") | gsub("</p><p>"; "\n\n")) + "\n" +
  "\n" +
  (if .reaction != null then
    "👍👎 REACTION: " + .reaction + "\n"
  else "" end) +
  (if .userComment != null then
    "💭 USER COMMENT: " + .userComment + "\n"
  else "" end) +
  "\n" +
  "📚 SOURCES: " + (.source | length | tostring) + " sources" +
  (if (.source | length) > 0 then 
    "\n" + (.source | to_entries | map("   [" + (.key + 1 | tostring) + "] " + .value) | join("\n"))
  else "" end) +
  "\n\n" + 
  "================================================================================================\n\n"'
  
  echo ""
  echo "END OF REPORT"
  echo "================================================================================================"
  
} > "$TXT_OUTPUT"

echo "   ✅ Saved to: $TXT_OUTPUT"
echo ""

################################################################################
# CREATE CSV FILE
################################################################################

echo "📊 Creating CSV file for spreadsheet analysis..."

# Include all messages (not just those with feedback) for complete analysis
echo "$MESSAGES" | jq -r '
# CSV Header
["sessionId", "msgId", "timestamp", "userQuery", "responseContent", "reaction", "userComment", "source_count"],
# CSV Data (clean HTML tags from response)
(.[] | [
  .sessionId,
  .msgId,
  .timestamp,
  .userQuery,
  (.responseContent | gsub("<br><br>"; " ") | gsub("<br>"; " ") | gsub("</p><p>"; " ") | gsub("<[^>]*>"; "")),
  (.reaction // ""),
  (.userComment // ""),
  (.source | length)
])
| @csv' > "$CSV_OUTPUT"

echo "   ✅ Saved to: $CSV_OUTPUT"
echo ""

################################################################################
# DISPLAY SUMMARY
################################################################################

echo "================================================================================================"
echo "                                    SUMMARY"
echo "================================================================================================"
echo ""
echo "🚀 Environment: PRODUCTION"
echo "🌐 URL: $PROD_URL"
echo "📊 Total Messages: $TOTAL_COUNT"
echo "💬 Messages with Feedback: $FEEDBACK_COUNT"
echo ""
echo "📄 Files Created:"
echo "   1. $TXT_OUTPUT (feedback entries only)"
echo "   2. $CSV_OUTPUT (all messages)"
echo ""
echo "📈 Feedback Statistics:"

# Get session count
SESSION_COUNT=$(echo "$MESSAGES" | jq '[.[].sessionId] | unique | length')
echo "   • Unique Sessions: $SESSION_COUNT"

# Get date range
FIRST_DATE=$(echo "$MESSAGES" | jq -r '.[-1].timestamp' | cut -d'T' -f1)
LAST_DATE=$(echo "$MESSAGES" | jq -r '.[0].timestamp' | cut -d'T' -f1)
echo "   • Date Range: $FIRST_DATE to $LAST_DATE"

# Get messages with sources
WITH_SOURCES=$(echo "$MESSAGES" | jq '[.[] | select((.source | length) > 0)] | length')
echo "   • Messages with Sources: $WITH_SOURCES"

# Reaction statistics
THUMBS_UP=$(echo "$MESSAGES" | jq '[.[] | select(.reaction == "thumbs_up")] | length')
THUMBS_DOWN=$(echo "$MESSAGES" | jq '[.[] | select(.reaction == "thumbs_down")] | length')
WITH_COMMENTS=$(echo "$MESSAGES" | jq '[.[] | select(.userComment != null)] | length')

echo ""
echo "👍 Reaction Breakdown:"
echo "   • Thumbs Up: $THUMBS_UP"
echo "   • Thumbs Down: $THUMBS_DOWN"
echo "   • With Comments: $WITH_COMMENTS"

# Calculate feedback rate
if [ "$TOTAL_COUNT" -gt 0 ]; then
    FEEDBACK_RATE=$(echo "scale=1; ($FEEDBACK_COUNT * 100) / $TOTAL_COUNT" | bc)
    echo "   • Feedback Rate: ${FEEDBACK_RATE}%"
fi

echo ""
echo "================================================================================================"
echo ""
echo "💡 To view the detailed report:"
echo "   cat $TXT_OUTPUT"
echo ""
echo "💡 To open CSV in Excel/Google Sheets:"
echo "   open $CSV_OUTPUT    (Mac)"
echo "   xdg-open $CSV_OUTPUT    (Linux)"
echo ""
echo "✅ Export complete!"
echo ""
