class MemoryManager:
    def __init__(self):
        self.sessions = {}

    async def create_session(self, session_id):
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
    async def get_latest_memory(self, session_id, read, travel=-1):
        try:
            options = {
                "content":("message","content"),
                "documents":("source_list","documents"),
                "sources":("source_list","sources")
            }
        
            latest_memory_entry=self.sessions[session_id][travel]

            level_a=options[read][0]
            level_b=options[read][1]
            requested_data=latest_memory_entry[level_a][level_b]

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
            if human_readable:  # Skip if human_readable is an empty string
                if url:
                    html += "<br>" + str(counter)  + ". " + human_readable + "<br>" + url
                    has_items=True
                    counter+=1

        if has_items:
            return html
        else:
            return "I did not use any specific sources in providing the information in the previous response."


