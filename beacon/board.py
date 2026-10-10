"""The community board: check-ins, needs, offers and reports from everyone on this Beacon,
and (with the mesh add-on) from Meshtastic radios nearby. Saved in data/board.json."""
import json
import re
import secrets
import threading
import time
from pathlib import Path

KINDS = ("checkin", "need", "offer", "report", "note", "mesh")
CHECKIN = re.compile(r"^\s*(safe|ok|help|sos)\b[\s:,-]*(.*)$", re.I | re.S)


class Board:
    def __init__(self, path: str | None, keep: int = 1000):
        self.path = Path(path) if path else None
        self.keep = keep
        self.lock = threading.Lock()
        self.posts: list[dict] = []
        if self.path and self.path.exists():
            try:
                self.posts = json.loads(self.path.read_text())
            except Exception:
                self.posts = []

    def _save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.posts, indent=1))
        tmp.replace(self.path)

    def add(self, kind: str, text: str, name: str = "", status: str = "", source: str = "beacon",
            ip: str = "", device: str = "", channel: int | None = None, mesh_id: str = "") -> dict:
        kind = kind if kind in KINDS else "note"
        if kind == "checkin":
            status = "help" if status == "help" else "safe"
        post = {"id": secrets.token_hex(5), "t": time.time(), "kind": kind,
                "name": " ".join(str(name).split())[:40], "text": str(text).strip()[:500],
                "status": status if kind == "checkin" else "", "source": source, "ip": ip, "device": device[:80],
                "channel": channel, "mesh_id": mesh_id[:20], "pinned": False, "resolved": False, "sent_mesh": False}
        with self.lock:
            self.posts.append(post)
            if len(self.posts) > self.keep:  # drop the oldest posts that aren't pinned
                drop = len(self.posts) - self.keep
                self.posts = [p for p in self.posts if p["pinned"] or (drop := drop - 1) < 0]
            self._save()
        return post

    def find(self, post_id: str) -> dict | None:
        return next((p for p in self.posts if p["id"] == post_id), None)

    def update(self, post_id: str, **changes) -> dict | None:
        with self.lock:
            p = self.find(post_id)
            if p:
                p.update(changes)
                self._save()
            return p

    def remove(self, post_id: str) -> bool:
        with self.lock:
            before = len(self.posts)
            self.posts = [p for p in self.posts if p["id"] != post_id]
            if len(self.posts) != before:
                self._save()
                return True
        return False

    def view(self, for_guest: bool) -> list[dict]:
        """Newest first, pinned on top. Guests don't see other people's network addresses."""
        posts = sorted(self.posts, key=lambda p: (not p["pinned"], -p["t"]))
        if for_guest:
            return [{k: v for k, v in p.items() if k not in ("ip", "device")} for p in posts]
        return [dict(p) for p in posts]

    def roster(self) -> list[dict]:
        """The latest check-in from each name, people who need help first."""
        latest: dict[str, dict] = {}
        for p in sorted(self.posts, key=lambda p: p["t"]):
            if p["kind"] == "checkin" and p["name"]:
                latest[p["name"].lower()] = p
        out = [{"name": p["name"], "status": p["status"], "t": p["t"], "text": p["text"], "source": p["source"]}
               for p in latest.values()]
        return sorted(out, key=lambda r: (r["status"] != "help", -r["t"]))

    @staticmethod
    def parse_checkin(text: str) -> tuple[str, str] | None:
        """'SAFE Garcia family' -> ('safe', 'Garcia family'); 'HELP 4B insulin' -> ('help', '4B insulin')."""
        m = CHECKIN.match(text or "")
        if not m:
            return None
        return ("help" if m.group(1).lower() in ("help", "sos") else "safe"), m.group(2).strip()
