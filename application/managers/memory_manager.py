import uuid

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
        if session_id not in self.sessions:
            print(f"Creating new session for: {session_id}")
            self.sessions[session_id] = []
        else:
            print(f"Session already exists for: {session_id}, keeping history.")


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
    

    async def format_sources_as_html(self, source_list):
        html = "Here are some of the sources I used for my previous answer:<br>"
        has_items = False
        counter = 1
        for source in source_list:
            human_readable = source["human_readable"]
            url = source["url"]
            filename = source.get("filename", "")
            
            # Use human_readable if available, otherwise fall back to filename
            display_name = human_readable if human_readable else filename
            
            if display_name:  # Only display if we have something to show
                html += "<br>" + str(counter) + ". " + display_name
                if url:
                    html += "<br>" + url
                has_items = True
                counter += 1

        if has_items:
            return html
        else:
            return "I did not use any specific sources in providing the information in the previous response."


