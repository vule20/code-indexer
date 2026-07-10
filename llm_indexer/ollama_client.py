import json
import logging
import requests
from typing import Generator, List, Dict, Any

from llm_indexer.config import OLLAMA_BASE_URL, EMBEDDING_MODEL, LLM_MODEL

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip('/')
        
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts using the /api/embed endpoint.
        Splits into smaller batches to prevent HTTP payload or timeout limits.
        """
        if not texts:
            return []
            
        embeddings = []
        batch_size = 64  # Batch size for embeddings
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            url = f"{self.base_url}/api/embed"
            payload = {
                "model": EMBEDDING_MODEL,
                "input": batch
            }
            try:
                response = requests.post(url, json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()
                if "embeddings" in data:
                    embeddings.extend(data["embeddings"])
                else:
                    raise KeyError(f"Expected 'embeddings' key in response, got: {data.keys()}")
            except Exception as e:
                logger.error(f"Error calling Ollama embed API for batch {i//batch_size}: {e}")
                # Fallback: try individual embeddings if batch fails
                for text in batch:
                    try:
                        single_url = f"{self.base_url}/api/embeddings"
                        single_payload = {
                            "model": EMBEDDING_MODEL,
                            "prompt": text
                        }
                        single_resp = requests.post(single_url, json=single_payload, timeout=30)
                        single_resp.raise_for_status()
                        embeddings.append(single_resp.json()["embedding"])
                    except Exception as single_err:
                        logger.error(f"Error on fallback embedding: {single_err}")
                        # Append a zero vector of appropriate size (nomic-embed-text is 768 dimensions)
                        embeddings.append([0.0] * 768)
                        
        return embeddings

    def chat_stream(self, system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
        """
        Stream chat responses from Ollama using the /api/chat endpoint.
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": True,
            "options": {
                "temperature": 0.2,
                "num_ctx": 16384
            }
        }
        
        try:
            response = requests.post(url, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.error(f"Error in Ollama chat stream: {e}")
            yield f"\n[Error streaming from LLM: {str(e)}]"

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Get complete chat response from Ollama (non-streaming).
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 16384
            }
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except Exception as e:
            logger.error(f"Error in Ollama chat: {e}")
            return f"Error communicating with local LLM: {str(e)}"
