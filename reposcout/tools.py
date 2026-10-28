import ast
import fnmatch
import re

SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
SECRET_FILE = re.compile(r"(^|/)(\.env.*|.*\.pem|.*\.key|id_rsa.*)$")
NOISE = {".mo", ".po", ".pot", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".lock", ".css", ".map",
         ".pth", ".pt", ".bin", ".onnx", ".zip", ".gz", ".pdf", ".mp4"}
LOCAL_TOOLS = {"list_files", "read_file", "search_code"}


class RepoTools:
    def __init__(self, root):
        self.root = root.resolve()

    def hidden(self, p):
        rel = p.relative_to(self.root)
        return any(part in SKIP for part in rel.parts) or SECRET_FILE.search(rel.as_posix())

    def path(self, rel):
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"{rel} is outside the repository")
        if self.hidden(p):
            raise ValueError(f"{rel} is not allowed")
        return p

    def files(self, base):
        return [p for p in sorted(base.rglob("*")) if not self.hidden(p)]

    def list_files(self, path=".", max_depth=3):
        base = self.path(path)
        lines = []
        for p in self.files(base):
            depth = len(p.relative_to(base).parts)
            if depth <= int(max_depth):
                lines.append("  " * (depth - 1) + p.name + ("/" if p.is_dir() else ""))
        return "\n".join(lines[:300]) or "(empty)"

    def read_file(self, path, start_line=1):
        p = self.path(path)
        if not p.is_file():
            raise ValueError(f"{path} not found, use list_files or search_code first")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line))
        end = min(start + 199, len(lines))
        more = f" (more: start_line={end + 1})" if end < len(lines) else ""
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        return f"{path} lines {start}-{end} of {len(lines)}{more}\n{body}"

    def search_code(self, pattern, glob=None):
        rx = re.compile(pattern, re.IGNORECASE)
        hits = []
        for p in self.files(self.root):
            rel = p.relative_to(self.root).as_posix()
            if (not p.is_file() or p.suffix.lower() in NOISE or p.stat().st_size > 1_000_000
                    or (glob and not fnmatch.fnmatch(rel, glob))):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                    if len(hits) == 40:
                        return "\n".join(hits) + "\n(stopped at 40 results)"
        return "\n".join(hits) or "No matches."

    def repo_map(self, max_chars=4000):
        lines = []
        for p in self.files(self.root):
            rel = p.relative_to(self.root)
            if p.is_dir() or p.suffix.lower() in NOISE or any(part.startswith(".") for part in rel.parts):
                continue
            entry = rel.as_posix()
            if p.suffix == ".py" and (names := top_level_names(p)):
                entry += ": " + ", ".join(names[:12])
            lines.append(entry)
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[:max_chars].rsplit("\n", 1)[0] + "\n(truncated)"


def top_level_names(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return []
    return [f"class {n.name}" if isinstance(n, ast.ClassDef) else f"def {n.name}"
            for n in tree.body
            if isinstance(n, ast.ClassDef)
            or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_"))]


SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files and folders in the repository as a tree.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Folder relative to the repo root, default '.'"},
            "max_depth": {"type": "integer", "description": "Default 3"}}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read up to 200 lines of a file, with line numbers. Use start_line to read further.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Case-insensitive regex search in all files. Returns path:line: text.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "e.g. 'def naturalsize'"},
            "glob": {"type": "string", "description": "Optional file filter, e.g. '*.py'"}},
            "required": ["pattern"]}}},
]
