import json
import requests
import logging
from typing import Generator, List, Dict

logger = logging.getLogger(__name__)

class OpenRouterClient:
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1"
        
    def chat_stream(self, system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> Generator[str, None, None]:
        """
        Stream chat responses from OpenRouter.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/google/llm-indexer",
            "X-Title": "LLM Indexer"
        }
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                decoded = line.decode('utf-8').strip()
                if decoded.startswith("data: "):
                    data_str = decoded[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error in OpenRouter chat stream: {e}")
            yield f"\n[Error streaming from OpenRouter: {str(e)}]"

    def chat(self, system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> str:
        """
        Get chat response from OpenRouter (non-streaming).
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/google/llm-indexer",
            "X-Title": "LLM Indexer"
        }
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            return "No choices returned from OpenRouter."
        except Exception as e:
            logger.error(f"Error in OpenRouter chat: {e}")
            return f"Error communicating with OpenRouter: {str(e)}"
