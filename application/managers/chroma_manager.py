import re
import asyncio
import logging
from langchain_community.vectorstores import Chroma
from mappings.knowledge_sources import knowledge_sources

class ChromaManager():
    def __init__(self, persist_directory, embedding_function, collection_name="langchain", *args, **kwargs):
        self.vectordb = Chroma(
            persist_directory=persist_directory, 
            embedding_function=embedding_function,
            collection_name=collection_name
        )
        
        super().__init__(*args,**kwargs)
    
    def parse_source(self,source):
        pattern = r'[\\/]+([^\\/]+\.pdf)$' #used windows OS to upload to chromaDB so used \,eg:newData\\NCA5_Ch28_Southwest_esp.pdf
        #stick to that pattern, if using a different convention then change regex to include this and your converntion.

        match = re.search(pattern, source)
        if match:
            filename = match.group(1)
            mapping_entry = knowledge_sources.get(
                filename, 
                {"url":"","description": ""}
            )
            
            payload = {
                "full_path":source,
                "filename":filename,
                "url": mapping_entry.get("url", ""),
                "human_readable": mapping_entry.get("description", filename)
            }
            return payload
        else:
            payload = {
                "full_path": source,
                "filename": "",
                "url": "",
                "human_readable": "",
            }
            return payload
        
    async def ann_search(self, user_query, k=4):
        # Run the synchronous similarity_search in an executor to avoid blocking
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # If no event loop exists, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            docs = await loop.run_in_executor(
                None, 
                self.vectordb.similarity_search, 
                user_query, 
                k
            )
        except Exception as e:
            # Log error and return empty results if search fails
            logging.error(f"ChromaDB similarity_search failed: {str(e)}")
            return {
                "documents": [],
                "sources": []
            }
        
        # Handle empty results gracefully
        if not docs:
            return {
                "documents": [],
                "sources": []
            }
        
        sources = [doc.metadata.get("source", "") for doc in docs if doc.metadata.get("source")]

        # Map to human readable; if source is not in the mapping use source name
        sources_parsed = [self.parse_source(source) for source in list(set(sources))]

        return {
            "documents": docs,
            "sources": sources_parsed
        }

    async def knowledge_to_string(self, docs, doc_field="documents"):
        target = docs.get(doc_field, [])
        if not target:
            return ""
        return " ".join([doc.page_content for doc in target if hasattr(doc, 'page_content')])