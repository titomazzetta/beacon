"""The archive: plans and answers saved on the drive, readable later with the AI off.

Each item is a small JSON file in data/archive. Items the Beacon computer saves are private
until it shares them (plans can contain household details). Items a guest saves are shared
with everyone on this Beacon, because a guest has no private space on someone else's drive.
"""
import json
import re
import secrets
import threading
import time
from pathlib import Path

ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
LIMITS = {"title": 200, "markdown": 120_000, "sources": 40}


def _clean_sources(sources) -> list[dict]:
    out = []
    for s in (sources or [])[:LIMITS["sources"]]:
        if isinstance(s, dict):
            out.append({k: str(s.get(k, ""))[:300] for k in ("kind", "book", "title", "ref", "page")})
    return out


class Archive:
    def __init__(self, folder: str):
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def _path(self, item_id: str) -> Path | None:
        return self.folder / f"{item_id}.json" if ID.match(item_id or "") else None

    def save(self, kind: str, title: str, markdown: str, sources=None, meta: dict | None = None,
             shared: bool = False, by: str = "host", device: str = "") -> dict:
        item_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        item = {"id": item_id, "kind": kind if kind in ("plan", "answer") else "answer",
                "title": str(title).strip()[:LIMITS["title"]] or "Untitled", "created": time.time(),
                "markdown": str(markdown)[:LIMITS["markdown"]], "sources": _clean_sources(sources),
                "meta": {str(k)[:40]: str(v)[:300] for k, v in (meta or {}).items()},
                "shared": bool(shared), "by": by, "device": device[:80]}
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._path(item_id).write_text(json.dumps(item, indent=1))
        return item

    def get(self, item_id: str) -> dict | None:
        p = self._path(item_id)
        if not p or not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def list(self, shared_only: bool = False) -> list[dict]:
        out = []
        if not self.folder.exists():
            return out
        for p in sorted(self.folder.glob("*.json"), reverse=True):
            try:
                it = json.loads(p.read_text())
            except Exception:
                continue
            if shared_only and not it.get("shared"):
                continue
            out.append({k: it.get(k) for k in ("id", "kind", "title", "created", "shared", "by", "device", "meta")})
        return out

    def set_shared(self, item_id: str, shared: bool) -> dict | None:
        with self.lock:
            it = self.get(item_id)
            if not it:
                return None
            it["shared"] = bool(shared)
            self._path(item_id).write_text(json.dumps(it, indent=1))
            return it

    def delete(self, item_id: str) -> bool:
        p = self._path(item_id)
        with self.lock:
            if p and p.exists():
                p.unlink()
                return True
        return False
