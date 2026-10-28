import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

WRITE_TOOLS = {"create_issue"}


@dataclass
class Config:
    name: str = "default"
    model: str = field(default_factory=lambda: os.getenv("REPOSCOUT_MODEL", ""))
    fallback_model: str = field(default_factory=lambda: os.getenv("REPOSCOUT_FALLBACK_MODEL", ""))
    max_steps: int = 10
    max_tokens: int = 60_000
    max_tool_chars: int = 6_000
    compact_after: int = 12_000
    keep_recent: int = 3
    repo_map: bool = True
    use_memory: bool = True
    guard: bool = True
