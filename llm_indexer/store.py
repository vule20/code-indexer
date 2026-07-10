import logging
import chromadb
from typing import List, Dict, Any, Optional

from llm_indexer.config import CHROMA_DB_PATH

logger = logging.getLogger(__name__)

class CodebaseVectorStore:
    def __init__(self, db_path: str = CHROMA_DB_PATH):
        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=self.db_path)

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize codebase name to meet ChromaDB collection naming rules:
        - 3-63 characters
        - starts and ends with alphanumeric
        - contains only alphanumeric, underscores, or hyphens
        - no consecutive dots
        """
        # Replace non-alphanumeric-dash-underscore characters with underscore
        sanitized = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
        # Strip leading/trailing non-alphanumeric
        while sanitized and not sanitized[0].isalnum():
            sanitized = sanitized[1:]
        while sanitized and not sanitized[-1].isalnum():
            sanitized = sanitized[:-1]
        
        # Ensure length constraint
        if len(sanitized) < 3:
            sanitized = f"col_{sanitized}"
        if len(sanitized) > 63:
            sanitized = sanitized[:63]
            while sanitized and not sanitized[-1].isalnum():
                sanitized = sanitized[:-1]
                
        return sanitized

    def get_or_create_collection(self, collection_name: str) -> Any:
        sanitized = self._sanitize_name(collection_name)
        return self.client.get_or_create_collection(
            name=sanitized,
            metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, collection_name: str, chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
        """
        Adds text chunks and their embeddings to the specified collection.
        """
        if not chunks:
            return
            
        collection = self.get_or_create_collection(collection_name)
        
        ids = [chunk["chunk_id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        
        # Extract metadata and ensure all values are primitives (ChromaDB requirement)
        metadatas = []
        for chunk in chunks:
            metadatas.append({
                "relative_path": chunk["relative_path"],
                "file_name": chunk["file_name"],
                "start_line": int(chunk["start_line"]),
                "end_line": int(chunk["end_line"]),
                "language": chunk["language"]
            })
            
        # Add to chroma. Chroma handles batching internally, but we can do it explicitly
        # if the size is very large.
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            collection.add(
                ids=ids[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
                documents=documents[i:i + batch_size]
            )
        logger.info(f"Added {len(chunks)} chunks to collection '{collection_name}' successfully.")

    def query(self, collection_name: str, query_embedding: List[float], n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Queries the collection for the nearest chunks.
        """
        collection = self.get_or_create_collection(collection_name)
        
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {e}")
            return []
            
        # Format results into a list of dictionaries
        formatted_results = []
        if not results or not results["documents"] or not results["documents"][0]:
            return []
            
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
        ids = results["ids"][0]
        distances = results["distances"][0] if results["distances"] else [0.0] * len(docs)
        
        for doc, meta, cid, dist in zip(docs, metas, ids, distances):
            formatted_results.append({
                "content": doc,
                "metadata": meta,
                "chunk_id": cid,
                "distance": dist
            })
            
        return formatted_results

    def list_collections(self) -> List[str]:
        """
        Returns names of all collections.
        """
        return [col.name for col in self.client.list_collections()]

    def get_collection_count(self, collection_name: str) -> int:
        """
        Returns number of documents in a collection.
        """
        sanitized = self._sanitize_name(collection_name)
        try:
            collection = self.client.get_collection(name=sanitized)
            return collection.count()
        except Exception:
            return 0

    def delete_collection(self, collection_name: str):
        """
        Deletes a collection.
        """
        sanitized = self._sanitize_name(collection_name)
        try:
            self.client.delete_collection(name=sanitized)
            logger.info(f"Deleted collection '{sanitized}' (original: '{collection_name}').")
        except Exception as e:
            logger.error(f"Error deleting collection '{sanitized}': {e}")
