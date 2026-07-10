import os
import time
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from llm_indexer.config import HOST, PORT, LLM_MODEL, EMBEDDING_MODEL
from llm_indexer.ollama_client import OllamaClient
from llm_indexer.parser import CodebaseParser
from llm_indexer.chunker import CodebaseChunker
from llm_indexer.store import CodebaseVectorStore
from llm_indexer.cli import format_context_snippets

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Codebase Indexer API")

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global indexing status tracker
indexing_status = {
    "status": "idle",  # idle, scanning, chunking, indexing, done, error
    "source_path": "",
    "collection_name": "",
    "total_files": 0,
    "total_chunks": 0,
    "processed_chunks": 0,
    "error_message": "",
    "time_elapsed": 0.0
}

class IndexRequest(BaseModel):
    path: str
    name: Optional[str] = None
    overwrite: Optional[bool] = False

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    collection: str
    message: str
    history: Optional[List[ChatMessage]] = []
    num_results: Optional[int] = 5

def run_indexing_in_background(path: str, collection_name: str, overwrite: bool):
    global indexing_status
    start_time = time.time()
    try:
        # 1. Scanning
        indexing_status.update({
            "status": "scanning",
            "source_path": path,
            "collection_name": collection_name,
            "total_files": 0,
            "total_chunks": 0,
            "processed_chunks": 0,
            "error_message": ""
        })
        parser = CodebaseParser(path)
        files = parser.scan_files()
        
        if not files:
            indexing_status.update({
                "status": "error",
                "error_message": "No supported files found in the directory."
            })
            return
            
        indexing_status["total_files"] = len(files)
        
        # 2. Chunking
        indexing_status["status"] = "chunking"
        chunker = CodebaseChunker()
        all_chunks = []
        for f in files:
            chunks = chunker.chunk_file(f)
            all_chunks.extend(chunks)
            
        if not all_chunks:
            indexing_status.update({
                "status": "error",
                "error_message": "No text chunks generated. Files might be empty."
            })
            return
            
        indexing_status["total_chunks"] = len(all_chunks)
        
        # 3. Embedding and Storing
        indexing_status["status"] = "indexing"
        store = CodebaseVectorStore()
        client = OllamaClient()
        
        if overwrite:
            store.delete_collection(collection_name)
            
        batch_size = 64
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            batch_texts = [c["content"] for c in batch]
            
            # Embed
            batch_embeddings = client.embed(batch_texts)
            # Store
            store.add_chunks(collection_name, batch, batch_embeddings)
            
            indexing_status["processed_chunks"] += len(batch)
            indexing_status["time_elapsed"] = round(time.time() - start_time, 2)
            
        indexing_status["status"] = "done"
        logger.info(f"Background indexing completed for {collection_name} in {time.time() - start_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Error during background indexing: {e}")
        indexing_status.update({
            "status": "error",
            "error_message": str(e),
            "time_elapsed": round(time.time() - start_time, 2)
        })

@app.get("/api/collections")
def list_collections():
    """
    List all indexed collections and their item counts.
    """
    store = CodebaseVectorStore()
    cols = store.list_collections()
    results = []
    for col in cols:
        count = store.get_collection_count(col)
        results.append({
            "name": col,
            "count": count
        })
    return {"collections": results}

@app.post("/api/index")
def trigger_index(req: IndexRequest, background_tasks: BackgroundTasks):
    """
    Trigger codebase indexing in the background.
    """
    global indexing_status
    if indexing_status["status"] in ("scanning", "chunking", "indexing"):
        raise HTTPException(status_code=400, detail="An indexing job is already running.")
        
    path = os.path.abspath(req.path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Path '{req.path}' does not exist.")
        
    collection_name = req.name or os.path.basename(path.rstrip(os.sep))
    if not collection_name:
        collection_name = "default_codebase"
        
    background_tasks.add_task(
        run_indexing_in_background,
        path,
        collection_name,
        req.overwrite
    )
    return {"message": "Indexing started in background.", "collection": collection_name}

@app.get("/api/index/status")
def get_index_status():
    """
    Get progress of current indexing job.
    """
    return indexing_status

@app.post("/api/chat")
async def chat_with_codebase(req: ChatRequest):
    """
    Stream answers about code snippets using Server-Sent Events (SSE).
    """
    store = CodebaseVectorStore()
    client = OllamaClient()
    
    # 1. Retrieve collection details
    count = store.get_collection_count(req.collection)
    if count == 0:
        raise HTTPException(
            status_code=404, 
            detail=f"Collection '{req.collection}' is empty or does not exist."
        )
        
    # 2. Embed user question
    query_embeddings = client.embed([req.message])
    if not query_embeddings:
        raise HTTPException(status_code=500, detail="Error generating embedding for question.")
        
    # 3. Query ChromaDB
    results = store.query(req.collection, query_embeddings[0], n_results=req.num_results)
    
    # Format snippet references to send as initial JSON payload
    references = []
    for idx, res in enumerate(results, 1):
        meta = res["metadata"]
        references.append({
            "index": idx,
            "relative_path": meta.get("relative_path"),
            "file_name": meta.get("file_name"),
            "start_line": meta.get("start_line"),
            "end_line": meta.get("end_line"),
            "language": meta.get("language"),
            "score": round(1 - res["distance"], 3),
            "content": res["content"]
        })
        
    # Map Pydantic history objects to standard dict list
    history_list = [{"role": msg.role, "content": msg.content} for msg in req.history] if req.history else None

    async def sse_generator():
        import json
        # Yield metadata reference structure first
        yield f"event: references\ndata: {json.dumps(references)}\n\n"
        
        # Yield the chat response stream
        context_str = format_context_snippets(results)
        system_prompt = (
            f"You are an expert software engineer assistant specializing in code explanation, debugging, and architecture design.\n"
            f"You are helping the user understand a codebase called '{req.collection}'.\n"
            f"Below are relevant code snippets retrieved from the codebase for context. Use these snippets to answer the user's question.\n"
            f"Refer to specific files and line numbers where appropriate.\n"
            f"Write clean code block formatting with proper language specifications.\n\n"
            f"Context:\n{context_str}"
        )
        
        for chunk in client.chat_stream(system_prompt, req.message, history=history_list):
            yield f"event: message\ndata: {json.dumps(chunk)}\n\n"
            
        yield "event: end\ndata: [DONE]\n\n"
        
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

# Mount Static Files (must be at the end, so it doesn't mask API routes)
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_path):
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
else:
    logger.warning("Static directory not found. Web interface won't be served.")
