# CODEINDEXER - HOW RUN

ME BUILD TOOL FOR INDEX CODE. YOU USE LOCAL BRAIN (OLLAMA).
HERE HOW RUN.

## 0. OLLAMA MUST RUN
Make sure Ollama run qwen2.5-coder and nomic-embed-text!
```bash
ollama run qwen2.5-coder:14b
ollama run nomic-embed-text:latest
```

## 1. INSTALL STUFF
```bash
pip install -r requirements.txt
```

## 2. CHOP CODES (INDEX)
You tell tool where code is. Tool chop code to chunks. Tool make embeddings.
```bash
python3 -m llm_indexer.cli index /path/to/your/codebase --name my-codebase
```
Example for mlir-aie:
```bash
python3 -m llm_indexer.cli index /home/vule/workspace/mlir-aie --name mlir-aie --overwrite
```

## 3. TALK TO CODE (CLI)
You ask question in black screen.

Single question:
```bash
python3 -m llm_indexer.cli query "how code work?" --name mlir-aie
```

Loop chat (type `exit` to stop):
```bash
python3 -m llm_indexer.cli chat --name mlir-aie
```

## 4. GORGEOUS WEB SCREEN (UI)
Start local web server:
```bash
python3 -m uvicorn llm_indexer.app:app --host 127.0.0.1 --port 8080
```
Open box in browser:
👉 http://127.0.0.1:8080
