import re
from langchain_community.vectorstores import Chroma
from mappings.knowledge_sources import knowledge_sources

class ChromaManager():
    def __init__(self, persist_directory, embedding_function, *args, **kwargs):
        self.vectordb = Chroma(persist_directory=persist_directory, embedding_function=embedding_function)
        
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
        
    async def ann_search(self, user_query):
        docs=self.vectordb.similarity_search(user_query)
        sources=[docs[i].metadata.get("source", "") for i in range(len(docs))]
        
        # Map to human readable; if source is not in the mapping use source name
        sources_parsed = [self.parse_source(source) for source in list(set(sources))]

        return {
            "documents":docs,
            "sources":sources_parsed
        }

    async def knowledge_to_string(self, docs, doc_field="documents"):
        target=docs[doc_field]
        return " ".join([target[i].page_content for i in range(len(target))])