"""Beacon links: Beacons on the same network sharing one Board.

A sub-Beacon links to a main Beacon the way a phone joins one: with the 4-digit code shown on the
main Beacon. It then pulls the main Board and pushes its own posts every few seconds, so check-ins,
needs and mesh messages reach everyone on either Beacon. Links form a star or a chain; every post's
origin travels with it, so nothing loops or doubles.

The main Beacon sees each linked Beacon in Connections, like any device, and can sign it out.
Links live on the local network only. Linking Beacons across the internet needs end-to-end
encryption and is planned separately (see ARCHITECTURE.md).
"""
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

COOKIE = "beacon_guest"
EVERY = 15          # seconds between syncs
PUSH_MAX = 40       # posts sent per sync
ORIGIN = re.compile(r"[0-9a-f]{8}:[0-9a-f]{10}")  # the Beacon a post started on, and its id there


def agent(name: str) -> str:
    return f"Beacon-link/1 ({re.sub(r'[^A-Za-z0-9 .,-]', '', name)[:40]})"


def normalize(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        url = "http://" + url
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", url):
        raise ValueError("Type the other Beacon's address, like beacon.local or 192.168.1.20:8643.")
    return url


def discover(seconds: float = 2.5) -> list[dict]:
    """Beacons that are sharing on this network, found with Bonjour (macOS dns-sd). Best effort."""
    if not shutil.which("dns-sd"):
        return []

    def run(args, wait):
        try:
            proc = subprocess.Popen(["dns-sd", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return ""
        time.sleep(wait)
        proc.terminate()
        try:
            return proc.communicate(timeout=2)[0]
        except Exception:
            proc.kill()
            return ""

    names = []
    for line in run(["-B", "_beacon._tcp", "local"], seconds).splitlines():
        m = re.search(r"\sAdd\s+\d+\s+\d+\s+\S+\s+_beacon\._tcp\.\s+(.+)$", line)
        if m and m.group(1).strip() not in names:
            names.append(m.group(1).strip())
    found = []
    for name in names[:12]:
        out = run(["-L", name, "_beacon._tcp", "local"], 1.5)
        m = re.search(r"can be reached at ([A-Za-z0-9.\-]+?)\.?:(\d+)", out)
        node = re.search(r"\bid=([0-9a-f]{8})", out)
        if m:
            port = "" if m.group(2) == "80" else f":{m.group(2)}"
            found.append({"name": name, "url": f"http://{m.group(1)}{port}", "node": node.group(1) if node else ""})
    return found


class Links:
    def __init__(self, path: str, board, node: dict, audit=None, http=requests):
        self.path, self.board, self.node, self.audit, self.http = Path(path), board, node, audit, http
        self.lock = threading.Lock()
        self.links: list[dict] = []
        self.thread = None
        try:
            self.links = json.loads(self.path.read_text())
        except Exception:
            self.links = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.links, indent=1))
        tmp.replace(self.path)

    def _headers(self, link: dict | None = None, json_body: bool = False) -> dict:
        h = {"User-Agent": agent(self.node["name"]), "X-Beacon": "1", "X-Beacon-Node": self.node["id"]}
        if link:
            h["Cookie"] = f"{COOKIE}={link['token']}"
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    # ------------------------------------------------------------ linking
    def link(self, url: str, code: str) -> dict:
        url = normalize(url)
        if not re.fullmatch(r"\d{4}", str(code or "")):
            raise ValueError("Enter the 4-digit code shown on the other Beacon.")
        r = self.http.get(f"{url}/?code={code}", headers=self._headers(), timeout=8, allow_redirects=False)
        m = re.search(COOKIE + r"=([A-Za-z0-9_\-]+)", r.headers.get("Set-Cookie", "") or "")
        if r.status_code not in (301, 302, 303) or not m:
            raise ValueError("That code didn't match, or that Beacon isn't sharing right now.")
        link = {"id": secrets.token_hex(4), "url": url, "token": m.group(1), "name": url.split("//", 1)[1],
                "node": "", "since": time.time(), "last_ok": 0, "error": "", "pulled": 0, "pushed": 0}
        hello = self.http.get(f"{url}/api/link/hello", headers=self._headers(link), timeout=8)
        if hello.status_code == 200:
            info = hello.json()
            if info.get("node") == self.node["id"]:
                raise ValueError("That's this Beacon.")
            link.update(node=str(info.get("node", ""))[:8], name=str(info.get("name", ""))[:40] or link["name"])
        with self.lock:
            self.links = [x for x in self.links if x["url"] != url] + [link]
            self._save()
        if self.audit:
            self.audit.add("link-added", "127.0.0.1", "", f"Linked to the Beacon {link['name']} at {url}")
        self.start()
        threading.Thread(target=self.sync_once, daemon=True).start()
        return self.public(link)

    def unlink(self, link_id: str) -> bool:
        with self.lock:
            before = len(self.links)
            self.links = [x for x in self.links if x["id"] != link_id]
            self._save()
            return len(self.links) != before

    # ------------------------------------------------------------ syncing
    def start(self):
        if self.thread and self.thread.is_alive():
            return

        def loop():
            while self.links:
                self.sync_once()
                time.sleep(EVERY)
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def sync_once(self):
        for link in list(self.links):
            try:
                self._sync(link)
                link.update(last_ok=time.time(), error="")
            except PermissionError:
                link["error"] = "Signed out by the other Beacon. Link again with its current code."
            except Exception as e:
                link["error"] = "Can't reach it right now." if "onnect" in str(e) or "imed out" in str(e) else str(e)[:120]
        with self.lock:
            self._save()

    def _sync(self, link: dict):
        r = self.http.get(f"{link['url']}/api/board", headers=self._headers(link), timeout=10)
        if r.status_code in (401, 403):
            raise PermissionError()
        if r.status_code != 200:
            raise RuntimeError(f"The other Beacon answered {r.status_code}.")
        remote = r.json().get("posts", [])
        theirs = set()
        for p in reversed(remote if isinstance(remote, list) else []):  # oldest first, so check-ins land in order
            origin = str(p.get("origin") or "") if isinstance(p, dict) else ""
            theirs.add(origin)
            if not ORIGIN.fullmatch(origin) or origin.startswith(self.node["id"] + ":"):
                continue
            added = self.board.add(p.get("kind", "note"), p.get("text", ""), name=p.get("name", ""), status=p.get("status", ""),
                                   source="link", via=p.get("via") or link["name"], origin=origin, t=p.get("t"))
            if added:
                link["pulled"] += 1
        mine = [p for p in self.board.view(for_guest=True)
                if p["origin"] not in theirs and p.get("via") != link["name"] and not p["origin"].startswith(link["node"] + ":")]
        if mine:
            body = [{k: p.get(k) for k in ("kind", "text", "name", "status", "origin", "via", "t")} for p in mine[:PUSH_MAX]]
            for p in body:
                p["via"] = p["via"] or self.node["name"]
            w = self.http.post(f"{link['url']}/api/link/posts", json={"posts": body}, headers=self._headers(link, True), timeout=10)
            if w.status_code in (401, 403):
                raise PermissionError()
            if w.status_code == 200:
                link["pushed"] += w.json().get("added", 0)

    # ------------------------------------------------------------ receiving (on the main Beacon)
    def receive(self, posts: list, sender: str, limit: int = PUSH_MAX) -> int:
        added = 0
        for p in (posts if isinstance(posts, list) else [])[:PUSH_MAX]:
            if added >= limit:
                break
            if not isinstance(p, dict) or not ORIGIN.fullmatch(str(p.get("origin", ""))):
                continue
            if str(p["origin"]).startswith(self.node["id"] + ":"):
                continue
            kind = str(p.get("kind", "note"))
            if kind == "checkin" and not str(p.get("name") or "").strip():
                continue
            if self.board.add(kind, str(p.get("text", "")), name=str(p.get("name", "")), status=str(p.get("status", "")),
                              source="link", via=str(p.get("via") or sender)[:40], origin=p["origin"], t=p.get("t")):
                added += 1
        return added

    def public(self, link: dict) -> dict:
        return {k: link.get(k) for k in ("id", "url", "name", "node", "since", "last_ok", "error", "pulled", "pushed")}

    def view(self) -> dict:
        return {"me": self.node, "links": [self.public(x) for x in self.links]}
