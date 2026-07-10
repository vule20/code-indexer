import os
import fnmatch
from typing import List, Dict, Any, Set

# Default directories to ignore
DEFAULT_IGNORE_DIRS = {
    ".git", ".github", ".vscode", ".idea", "node_modules", 
    "venv", ".venv", "ironenv", "build", "dist", "target", 
    "out", "CMakeFiles", "__pycache__", ".pytest_cache",
    "llvm", "third_party", "my_install", "install", "Work"
}

# Default file extensions to index
SUPPORTED_EXTENSIONS = {
    # C/C++
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx",
    # MLIR & Compilers
    ".mlir", ".td", ".ll",
    # Python
    ".py",
    # Go / Rust
    ".go", ".rs",
    # Web / Configs
    ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
    # Shell / Build
    ".sh", ".bash", ".txt", ".md", ".cmake"
}

# Extensions to explicitly ignore (binaries, caches, images, etc.)
EXCLUDED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".a", ".o", ".lib",
    ".log", ".db", ".sqlite", ".exe", ".bin"
}

class CodebaseParser:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.ignore_patterns = self._load_gitignore_patterns()

    def _load_gitignore_patterns(self) -> List[str]:
        """
        Loads patterns from .gitignore file at the root directory if it exists.
        """
        patterns = []
        gitignore_path = os.path.join(self.root_dir, ".gitignore")
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        # Skip comments and empty lines
                        if not line or line.startswith("#"):
                            continue
                        patterns.append(line)
            except Exception as e:
                print(f"Warning: Could not read .gitignore: {e}")
        return patterns

    def should_ignore(self, path: str) -> bool:
        """
        Checks if a file or directory path should be ignored based on default rules
        and .gitignore patterns.
        """
        rel_path = os.path.relpath(path, self.root_dir)
        parts = rel_path.split(os.sep)
        
        # 1. Check default ignore directories
        for part in parts:
            if part in DEFAULT_IGNORE_DIRS:
                return True

        # 2. Check if file is a known excluded extension
        _, ext = os.path.splitext(path)
        if ext.lower() in EXCLUDED_EXTENSIONS:
            return True

        # 3. Check gitignore patterns
        # Standardise rel_path to use forward slashes for matching
        match_path = rel_path.replace(os.sep, '/')
        for pattern in self.ignore_patterns:
            # Handle directory patterns ending in /
            if pattern.endswith('/'):
                dir_pattern = pattern.rstrip('/')
                if any(fnmatch.fnmatch(part, dir_pattern) for part in parts):
                    return True
            # Handle standard glob patterns
            if fnmatch.fnmatch(match_path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
            # Match sub-paths: if pattern is 'build', it matches 'path/to/build/file'
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True

        return False

    def scan_files(self) -> List[Dict[str, Any]]:
        """
        Recursively scans the codebase directory and returns lists of file metadata.
        """
        scanned_files = []
        
        for root, dirs, files in os.walk(self.root_dir):
            # Prune directories in place so os.walk doesn't traverse ignored directories
            dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]
            
            for file in files:
                file_path = os.path.join(root, file)
                if self.should_ignore(file_path):
                    continue
                
                # Filter by supported extensions or specific file names (like CMakeLists.txt)
                _, ext = os.path.splitext(file)
                ext = ext.lower()
                is_cmake = file.lower() == "cmakelists.txt"
                
                if ext in SUPPORTED_EXTENSIONS or is_cmake:
                    # Enforce size limits to skip massive weight tables, configs, or data mocks
                    try:
                        size = os.path.getsize(file_path)
                        if ext in (".txt", ".json", ".yaml", ".yml"):
                            if size >= 50 * 1024:
                                continue
                        else:
                            if size >= 300 * 1024:
                                continue
                    except OSError:
                        continue
                    
                    # Ingest language
                    lang = self._detect_language(file, ext)
                    scanned_files.append({
                        "absolute_path": file_path,
                        "relative_path": os.path.relpath(file_path, self.root_dir),
                        "file_name": file,
                        "language": lang
                    })
                    
        return scanned_files

    def _detect_language(self, filename: str, ext: str) -> str:
        """
        Infers language name from file extension or file name.
        """
        if filename.lower() == "cmakelists.txt" or ext == ".cmake":
            return "cmake"
        
        ext_map = {
            ".py": "python",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".h": "cpp",
            ".hpp": "cpp",
            ".hxx": "cpp",
            ".c": "c",
            ".mlir": "mlir",
            ".td": "tablegen",
            ".ll": "llvm-ir",
            ".go": "go",
            ".rs": "rust",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".sh": "bash",
            ".bash": "bash",
            ".md": "markdown",
            ".txt": "text"
        }
        return ext_map.get(ext, "text")
