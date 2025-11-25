import re
import asyncio
import logging
import time
from langchain_chroma import Chroma
from mappings.knowledge_sources import knowledge_sources

class ChromaManager():
    def __init__(self, persist_directory, embedding_function, collection_name="langchain", *args, **kwargs):
        logging.info(f"🔧 Initializing ChromaManager")
        logging.info(f"   Persist directory: {persist_directory}")
        logging.info(f"   Collection name: {collection_name}")
        
        try:
            self.vectordb = Chroma(
                persist_directory=persist_directory, 
                embedding_function=embedding_function,
                collection_name=collection_name,
                collection_metadata={"hnsw:space": "cosine"}
            )
            logging.info(f"✅ ChromaDB initialized successfully")
        except Exception as e:
            logging.error(f"❌ Failed to initialize ChromaDB: {str(e)}")
            raise
    
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
            
            if not mapping_entry.get("url"):
                logging.debug(f"⚠️  No URL mapping found for file: {filename}")
            
            return payload
        else:
            logging.warning(f"⚠️  Could not parse source path: {source}")
            payload = {
                "full_path": source,
                "filename": "",
                "url": "",
                "human_readable": "",
            }
            return payload
        
    async def ann_search(self, user_query, k=4):
        logging.info(f"🔍 Starting RAG similarity search")
        logging.info(f"   Query: '{user_query[:100]}{'...' if len(user_query) > 100 else ''}'")
        logging.info(f"   Top-K: {k}")
        logging.info(f"   Collection: {self.vectordb._collection.name if hasattr(self.vectordb, '_collection') else 'default'}")
        
        start_time = time.time()
        
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
            
            elapsed_time = time.time() - start_time
            logging.info(f"✅ Similarity search completed in {elapsed_time:.3f}s")
            logging.info(f"   Retrieved {len(docs)} document(s)")
            
        except Exception as e:
            # Log error and return empty results if search fails
            logging.error(f"❌ ChromaDB similarity_search failed: {str(e)}", exc_info=True)
            return {
                "documents": [],
                "sources": []
            }
        
        # Handle empty results gracefully
        if not docs:
            logging.warning(f"⚠️  No documents found for query: '{user_query[:50]}...'")
            return {
                "documents": [],
                "sources": []
            }
        
        # Extract and log document metadata
        logging.debug(f"📄 Document details:")
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "unknown")
            name = doc.metadata.get("name", "unknown")
            content_preview = doc.page_content[:100] + "..." if len(doc.page_content) > 100 else doc.page_content
            logging.debug(f"   {i}. Source: {name} | Path: {source} | Content preview: {content_preview}")
        
        sources = [doc.metadata.get("source", "") for doc in docs if doc.metadata.get("source")]
        unique_sources = list(set(sources))
        
        logging.info(f"📚 Found {len(unique_sources)} unique source(s) from {len(sources)} document(s)")

        # Map to human readable; if source is not in the mapping use source name
        sources_parsed = [self.parse_source(source) for source in unique_sources]
        
        # Log parsed sources
        logging.info(f"🔗 Parsed sources:")
        for i, source in enumerate(sources_parsed, 1):
            logging.info(f"   {i}. '{source.get('human_readable', 'N/A')}' -> {source.get('url', 'No URL')[:80]}...")

        return {
            "documents": docs,
            "sources": sources_parsed
        }

    async def knowledge_to_string(self, docs, doc_field="documents"):
        target = docs.get(doc_field, [])
        if not target:
            logging.warning(f"⚠️  No documents in field '{doc_field}' to convert to string")
            return ""
        
        logging.debug(f"📝 Converting {len(target)} document(s) to knowledge string")
        
        content_parts = []
        for i, doc in enumerate(target, 1):
            if hasattr(doc, 'page_content'):
                content_parts.append(doc.page_content)
                logging.debug(f"   Added document {i}: {len(doc.page_content)} characters")
            else:
                logging.warning(f"⚠️  Document {i} missing page_content attribute")
        
        result = " ".join(content_parts)
        logging.info(f"✅ Knowledge string created: {len(result)} total characters from {len(content_parts)} document(s)")
        
        return result