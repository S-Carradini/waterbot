import uuid
import logging

class MemoryManager:
    def __init__(self):
        self.sessions = {}
        self.message_counts = {}

    async def get_message_count(self, session_id):
        if session_id in self.message_counts:
            return self.message_counts[session_id]["count"]
        else:
            return 0
    async def get_message_count_uuid_combo(self, session_id):
        if session_id in self.message_counts:
            return str(self.message_counts[session_id]["conversation_uuid"]) + "." + str(self.message_counts[session_id]["count"])
        else:
            return "error." + str(uuid.uuid4())
    async def get_message_count_uuid(self,session_id):
        if session_id in self.message_counts:
            return self.message_counts[session_id]["conversation_uuid"]
        else:
            return "error." + str(uuid.uuid4())
             
    async def increment_message_count(self, session_id):
        if session_id in self.message_counts:
            self.message_counts[session_id]["count"] += 1
        else:
            conversation_uuid=str(uuid.uuid4())
            self.message_counts[session_id] = {
                "conversation_uuid":conversation_uuid,
                "count":0
            }

    async def create_session(self, session_id):
        # Session IDs are credentials; never write them to the logs.
        if session_id not in self.sessions:
            self.sessions[session_id] = []


    async def add_message_to_session(self, session_id, message, source_list):
        if session_id not in self.sessions:
            await self.create_session(session_id)

        self.sessions[session_id].append(
            {
                "message":message,
                "source_list":source_list
            }
        )

    async def get_session_history_all(self, session_id, field="message"):
        if session_id in self.sessions:
            return [entry[field] for entry in self.sessions[session_id]]
        else:
            return []
    
    # Get history
    # default last bot response
    async def get_latest_memory(self, session_id, read, travel=-1, layers=2):
        try:
            options = {
                "content":("message","content"),
                "documents":("source_list","documents"),
                "sources":("source_list","sources")
            }
        
            latest_memory_entry=self.sessions[session_id][travel]

            level_a=options[read][0]
            level_b=options[read][1]

            if( layers == 2 ):
                requested_data=latest_memory_entry[level_a][level_b]
            elif( layers == 1):
                requested_data=latest_memory_entry[level_a]
            elif( layers == 0 ):
                requested_data=latest_memory_entry

            return requested_data
        except:
            return ""
    

    # ------------------------------------------------------------------
    # Blue (WaterBot) turns. Each Blue entry carries a "meta" dict so the
    # follow-up buttons can see whether the question they belong to was
    # refused, and so the history sent to the model contains only real
    # turns (no refused questions, no tag-wrapped pseudo messages).
    # Riverbot entries have no "meta" and are ignored by these helpers.
    # ------------------------------------------------------------------
    async def add_blue_turn(self, session_id, user_content, assistant_content, source_list, meta):
        """Store one user/assistant exchange with shared metadata."""
        if session_id not in self.sessions:
            await self.create_session(session_id)
        turn_meta = dict(meta)
        self.sessions[session_id].append({
            "message": {"role": "user", "content": user_content},
            "source_list": [],
            "meta": {**turn_meta, "side": "user"},
        })
        self.sessions[session_id].append({
            "message": {"role": "assistant", "content": assistant_content},
            "source_list": source_list,
            "meta": {**turn_meta, "side": "assistant"},
        })

    def _blue_entries(self, session_id):
        return [e for e in self.sessions.get(session_id, []) if isinstance(e.get("meta"), dict)]

    async def blue_history(self, session_id, max_turns=10):
        """Answered (not refused) chat and follow-up exchanges, oldest first, capped."""
        entries = self._blue_entries(session_id)
        messages = []
        for i in range(0, len(entries) - 1):
            user, assistant = entries[i], entries[i + 1]
            if user["meta"].get("side") != "user" or assistant["meta"].get("side") != "assistant":
                continue
            meta = user["meta"]
            if meta.get("refused") or meta.get("kind") == "sources":
                continue
            messages.append([user["message"], assistant["message"]])
        flattened = []
        for pair in messages[-max_turns:]:
            flattened.extend(pair)
        return flattened

    async def recent_blue_questions(self, session_id, limit=2):
        """The user's latest typed questions (refused ones included), for screening context."""
        questions = [
            e["meta"].get("original_query", "")
            for e in self._blue_entries(session_id)
            if e["meta"].get("side") == "user" and e["meta"].get("kind") == "chat"
        ]
        return [q for q in questions if q][-limit:]

    async def blue_follow_up_count(self, session_id):
        """Follow-up button clicks recorded in this session (refused ones included)."""
        return sum(
            1 for e in self._blue_entries(session_id)
            if e["meta"].get("side") == "user" and e["meta"].get("kind") != "chat"
        )

    async def last_blue_parent(self, session_id):
        """Metadata of the latest typed question's exchange, or None.

        Returns the assistant-side entry, whose meta holds the screening result,
        the answer, the retrieved documents and the follow-up counter.
        """
        for entry in reversed(self._blue_entries(session_id)):
            meta = entry["meta"]
            if meta.get("kind") == "chat" and meta.get("side") == "assistant":
                return entry
        return None

    async def format_sources_as_html(self, source_list):
        logging.info(f"📚 Formatting sources: Received {len(source_list) if source_list else 0} sources from RAG")
        
        # Handle None or empty source list
        if not source_list:
            logging.warning("⚠️  No sources provided (empty or None)")
            return "I did not use any specific sources in providing the information in the previous response."
        
        html = "Here are some of the sources I used for my previous answer:<br>"
        has_items = False
        counter = 1
        seen_urls = set()  # Track URLs we've already added
        duplicate_count = 0
        
        for source in source_list:
            # Skip if source is not a dict or missing required fields
            if not isinstance(source, dict):
                continue
                
            human_readable = source.get("human_readable", "")
            url = source.get("url", "")
            if human_readable:  # Skip if human_readable is an empty string
                dedup_key = url or human_readable
                if dedup_key not in seen_urls:
                    entry = "<br>" + str(counter) + ". " + human_readable
                    if url:
                        entry += "<br>" + url
                    html += entry
                    has_items = True
                    counter += 1
                    seen_urls.add(dedup_key)
                    logging.info(f"  ✓ Added source {counter-1}: '{human_readable}'" + (f" -> {url}" if url else " (no URL)"))
                else:
                    duplicate_count += 1
                    logging.debug(f"  ⊗ Skipped duplicate: '{human_readable}'")

        if duplicate_count > 0:
            logging.info(f"🔄 Deduplication: Removed {duplicate_count} duplicate source(s) with same URL")
        
        logging.info(f"📋 Final result: {len(seen_urls)} unique source(s) displayed out of {len(source_list)} total")

        if has_items:
            return html
        else:
            logging.warning("⚠️  No valid sources found to display")
            return "I did not use any specific sources in providing the information in the previous response."


