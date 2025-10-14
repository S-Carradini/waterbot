#!/bin/bash
################################################################################
# Waterbot Database Messages Exporter
# Creates both detailed TXT report and CSV file
################################################################################

# Get the directory where THIS script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Configuration
CLOUDFRONT_URL="https://djl31v9y2vbwy.cloudfront.net"
USERNAME="admin"
PASSWORD="supersecurepassword"
TXT_OUTPUT="$SCRIPT_DIR/database_messages_detailed.txt"
CSV_OUTPUT="$SCRIPT_DIR/database_messages.csv"

echo "📁 Saving files to: $SCRIPT_DIR"
echo ""

echo "================================================================================================"
echo "                    WATERBOT DATABASE MESSAGES EXPORTER"
echo "================================================================================================"
echo ""
echo "📊 Fetching messages from PostgreSQL RDS (us-west-2)..."
echo ""

# Fetch messages from API
MESSAGES=$(curl -s -u "$USERNAME:$PASSWORD" "$CLOUDFRONT_URL/messages")

# Check if fetch was successful
if [ -z "$MESSAGES" ] || [ "$MESSAGES" == "null" ]; then
    echo "❌ Error: Could not fetch messages from database"
    exit 1
fi

COUNT=$(echo "$MESSAGES" | jq 'length')

if [ "$COUNT" == "null" ] || [ "$COUNT" == "0" ]; then
    echo "⚠️  No messages found in database"
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
  echo "                    WATERBOT DATABASE MESSAGES - DEV (us-west-2)"
  echo "================================================================================================"
  echo ""
  echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Total Messages: $COUNT"
  echo "Database: PostgreSQL RDS"
  echo "Region: us-west-2"
  echo ""
  echo "================================================================================================"
  echo ""
  
  # Loop through each message
  echo "$MESSAGES" | jq -r '.[] | 
  "MESSAGE #" + (.id | tostring) + "\n" +
  "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
  "Session UUID:  " + .session_uuid + "\n" +
  "Message ID:    " + .msg_id + "\n" +
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
["id", "session_uuid", "msg_id", "user_query", "response_content", "source_count", "created_at"],
# CSV Data (clean HTML tags from response)
(.[] | [
  .id,
  .session_uuid,
  .msg_id,
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
echo "📊 Total Messages: $COUNT"
echo ""
echo "📄 Files Created:"
echo "   1. $TXT_OUTPUT (detailed human-readable report)"
echo "   2. $CSV_OUTPUT (spreadsheet-compatible format)"
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