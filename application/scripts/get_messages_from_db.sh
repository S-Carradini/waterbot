#!/bin/bash
################################################################################
# Waterbot Database Messages Exporter - PRODUCTION
# Creates both detailed TXT report and CSV file
################################################################################

#RUN: bash ./application/scripts/get_messages_from_db.sh

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

# Configuration (now loaded from environment)
PROD_URL="${PROD_URL:-https://azwaterbot.org}"
USERNAME="${API_USERNAME}"
PASSWORD="${API_PASSWORD}"
TXT_OUTPUT="$SCRIPT_DIR/prod_database_messages_detailed.txt"
CSV_OUTPUT="$SCRIPT_DIR/prod_database_messages.csv"

echo "================================================================================================"
echo "                    WATERBOT DATABASE MESSAGES EXPORTER - PRODUCTION"
echo "================================================================================================"
echo ""
echo "📁 Saving files to: $SCRIPT_DIR"
echo "📊 Fetching messages from PostgreSQL RDS (us-east-1)..."
echo ""

# Fetch messages from API
MESSAGES=$(curl -s -u "$USERNAME:$PASSWORD" "$PROD_URL/messages")

# Check if fetch was successful
if [ -z "$MESSAGES" ]; then
    echo "❌ Error: No response from $PROD_URL/messages"
    echo "   This might mean:"
    echo "   • Production is not deployed yet"
    echo "   • Network connectivity issue"
    echo ""
    echo "💡 Debug: curl -v -u \"\$API_USERNAME:\$API_PASSWORD\" \"$PROD_URL/messages\""
    exit 1
fi

if [ "$MESSAGES" == "null" ]; then
    echo "❌ Error: API returned null (database error on server side)"
    echo "   This means the /messages endpoint hit a database exception."
    echo "   Check Railway logs for the production service."
    exit 1
fi

# Ensure response is a JSON array (reject 401/500 error bodies like {"detail":"Unauthorized"})
if ! echo "$MESSAGES" | jq -e 'type == "array"' >/dev/null 2>&1; then
    echo "❌ Error: API did not return a message list (likely auth failed)."
    echo "   Set API_USERNAME and API_PASSWORD in your .env to match the backend."
    echo "   See application/sample.env for the expected variable names."
    exit 1
fi

COUNT=$(echo "$MESSAGES" | jq 'length')

if [ "$COUNT" == "null" ] || [ "$COUNT" == "0" ]; then
    echo "⚠️  No messages found in production database"
    echo "   Database is empty - no users have chatted yet"
    exit 0
fi

echo "✅ Found $COUNT messages"
echo ""

################################################################################
# CREATE DETAILED TXT REPORT
################################################################################

echo "📄 Creating detailed TXT report..."

{
  echo "================================================================================================"
  echo "                    WATERBOT DATABASE MESSAGES - PRODUCTION (us-east-1)"
  echo "================================================================================================"
  echo ""
  echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Total Messages: $COUNT"
  echo "Database: PostgreSQL RDS"
  echo "Region: us-east-1"
  echo "URL: https://azwaterbot.org"
  echo ""
  echo "================================================================================================"
  echo ""
  
  # Loop through each message
  echo "$MESSAGES" | jq -r '.[] | 
  "MESSAGE #" + (.id | tostring) + "\n" +
  "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
  "Session UUID:  " + .session_uuid + "\n" +
  "Message ID:    " + .msg_id + "\n" +
  "Chatbot Type:  " + (.chatbot_type // "waterbot") + "\n" +
  "Created At:    " + .created_at + "\n" +
  "\n" +
  "👤 USER QUERY:\n" + .user_query + "\n" +
  "\n" +
  "🤖 BOT RESPONSE:\n" + (.response_content | gsub("<br><br>"; "\n\n") | gsub("<br>"; "\n") | gsub("</p><p>"; "\n\n")) + "\n" +
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

echo "$MESSAGES" | jq -r '
# CSV Header
["id", "session_uuid", "msg_id", "chatbot_type", "user_query", "response_content", "source_count", "created_at"],
# CSV Data (clean HTML tags from response)
(.[] | [
  .id,
  .session_uuid,
  .msg_id,
  (.chatbot_type // "waterbot"),
  .user_query,
  (.response_content | gsub("<br><br>"; " ") | gsub("<br>"; " ") | gsub("</p><p>"; " ") | gsub("<[^>]*>"; "")),
  (.source | length),
  .created_at
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
echo "🚀 Environment: PRODUCTION (us-east-1)"
echo "🌐 URL: https://azwaterbot.org"
echo "📊 Total Messages: $COUNT"
echo ""
echo "📄 Files Created:"
echo "   1. $TXT_OUTPUT"
echo "   2. $CSV_OUTPUT"
echo ""
echo "📈 Statistics:"

# Get session count
SESSION_COUNT=$(echo "$MESSAGES" | jq '[.[].session_uuid] | unique | length')
echo "   • Unique Sessions: $SESSION_COUNT"

# Get date range
FIRST_DATE=$(echo "$MESSAGES" | jq -r '.[-1].created_at' | cut -d'T' -f1)
LAST_DATE=$(echo "$MESSAGES" | jq -r '.[0].created_at' | cut -d'T' -f1)
echo "   • Date Range: $FIRST_DATE to $LAST_DATE"

# Get messages with sources
WITH_SOURCES=$(echo "$MESSAGES" | jq '[.[] | select((.source | length) > 0)] | length')
echo "   • Messages with Sources: $WITH_SOURCES"

# ✅ NEW: Show chatbot type breakdown
echo ""
echo "📊 Chatbot Type Breakdown:"
WATERBOT_COUNT=$(echo "$MESSAGES" | jq '[.[] | select((.chatbot_type // "waterbot") == "waterbot")] | length')
RIVERBOT_COUNT=$(echo "$MESSAGES" | jq '[.[] | select(.chatbot_type == "riverbot")] | length')
echo "   • Waterbot: $WATERBOT_COUNT messages"
echo "   • Riverbot: $RIVERBOT_COUNT messages"

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