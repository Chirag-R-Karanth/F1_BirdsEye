from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(os.getenv("F1_CACHE_DIR", Path(__file__).resolve().parent.parent / "cache"))

class Cache:
    def __init__(self, session_key: int):
        self.root = ROOT / str(session_key)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def load(self, name: str):
        p = self.path(name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, name: str, data) -> None:
        p = self.path(name)
        fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
