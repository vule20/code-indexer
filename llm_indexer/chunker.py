import os
from typing import List, Dict, Any
from llm_indexer.config import CHUNK_SIZE, CHUNK_OVERLAP

class CodebaseChunker:
    def __init__(self, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_file(self, file_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Reads a file and splits its content into line-aware chunks.
        """
        abs_path = file_info["absolute_path"]
        rel_path = file_info["relative_path"]
        file_name = file_info["file_name"]
        language = file_info["language"]

        chunks = []
        
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Warning: Failed to read {abs_path}: {e}")
            return []

        if not lines:
            return []

        current_lines = []
        current_char_count = 0
        start_line = 1
        
        line_idx = 0
        while line_idx < len(lines):
            line = lines[line_idx]
            line_len = len(line)
            
            # If a single line is exceptionally long (e.g. minified JS or large generated data),
            # we handle it separately to avoid infinite loops or massive chunks
            if line_len > self.chunk_size:
                # Flush existing chunk if any
                if current_lines:
                    chunks.append(self._create_chunk_dict(
                        current_lines, start_line, line_idx, rel_path, file_name, language
                    ))
                    current_lines = []
                    current_char_count = 0
                
                # Split the huge line into chunk-sized pieces
                for sub_idx, offset in enumerate(range(0, line_len, self.chunk_size)):
                    sub_content = line[offset:offset + self.chunk_size]
                    chunks.append({
                        "content": sub_content,
                        "relative_path": rel_path,
                        "file_name": file_name,
                        "start_line": line_idx + 1,
                        "end_line": line_idx + 1,
                        "language": language,
                        "chunk_id": f"{rel_path}:{line_idx + 1}-part{sub_idx}"
                    })
                start_line = line_idx + 2
                line_idx += 1
                continue
                
            # If adding this line would exceed the chunk size, flush the current chunk
            if current_char_count + line_len > self.chunk_size and current_lines:
                chunks.append(self._create_chunk_dict(
                    current_lines, start_line, line_idx, rel_path, file_name, language
                ))
                
                # Setup next chunk with overlap
                # Backtrack to create overlap
                overlap_chars = 0
                overlap_lines = []
                overlap_idx = line_idx - 1
                
                while overlap_idx >= start_line - 1 and overlap_idx >= 0:
                    overlap_line = lines[overlap_idx]
                    if overlap_chars + len(overlap_line) > self.chunk_overlap:
                        break
                    overlap_lines.insert(0, overlap_line)
                    overlap_chars += len(overlap_line)
                    overlap_idx -= 1
                
                current_lines = overlap_lines
                current_char_count = overlap_chars
                start_line = overlap_idx + 2  # 1-indexed next line after overlap start
            
            # Add line to current chunk
            current_lines.append(line)
            current_char_count += line_len
            line_idx += 1

        # Flush any remaining lines
        if current_lines:
            chunks.append(self._create_chunk_dict(
                current_lines, start_line, len(lines), rel_path, file_name, language
            ))

        return chunks

    def _create_chunk_dict(
        self, 
        lines: List[str], 
        start_line: int, 
        end_line: int, 
        rel_path: str, 
        file_name: str, 
        language: str
    ) -> Dict[str, Any]:
        """
        Helper to construct a chunk dictionary.
        """
        content = "".join(lines)
        return {
            "content": content,
            "relative_path": rel_path,
            "file_name": file_name,
            "start_line": start_line,
            "end_line": end_line,
            "language": language,
            "chunk_id": f"{rel_path}:{start_line}-{end_line}"
        }
