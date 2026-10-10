"""Library Manager: catalog of bands/tiers, live Kiwix lookups, resumable downloads."""
import json
import re
import shutil
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .config import ROOT

OPDS = "https://library.kiwix.org/catalog/v2/entries"
TIER_ORDER = ["core", "extended", "complete", "everything"]
UA = {"User-Agent": "Beacon-offline-library/0.2 (+https://github.com)"}


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or ROOT / "catalog.json").read_text())


def all_items(catalog: dict) -> list[dict]:
    out = []
    for band in catalog["bands"]:
        for item in band["items"]:
            out.append({**item, "band": band["id"], "band_title": band["title"]})
    return out


def items_for_tier(catalog: dict, tier: str, bands: list[str] | None = None) -> list[dict]:
    """Downloadable items up to and including `tier`. Optional items (e.g. Wikipedia with
    images) are never auto-selected, and only one item per exclusive group is chosen:
    the largest tier that qualifies."""
    limit = TIER_ORDER.index(tier)
    chosen, groups = [], {}
    for it in all_items(catalog):
        if it["type"] == "link" or it.get("optional"):
            continue
        if bands and it["band"] not in bands:
            continue
        if TIER_ORDER.index(it["tier"]) > limit:
            continue
        g = it.get("group")
        if g:
            prev = groups.get(g)
            if prev is None or TIER_ORDER.index(it["tier"]) >= TIER_ORDER.index(prev["tier"]):
                if prev:
                    chosen.remove(prev)
                groups[g] = it
                chosen.append(it)
        else:
            chosen.append(it)
    return chosen


# ------------------------------------------------------------------ Kiwix catalog (OPDS)

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_opds(xml_text: str) -> list[dict]:
    """Parse a Kiwix OPDS v2 feed into simple dicts (namespace-agnostic)."""
    root = ET.fromstring(xml_text)
    entries = []
    for e in root:
        if _local(e.tag) != "entry":
            continue
        d = {"name": "", "flavour": "", "title": "", "updated": "", "url": "", "size": 0,
             "language": "", "summary": "", "articles": 0}
        for child in e:
            tag = _local(child.tag)
            if tag in ("name", "flavour", "title", "updated", "language", "summary"):
                d[tag] = (child.text or "").strip()
            elif tag == "articleCount":
                d["articles"] = int(child.text or 0)
            elif tag == "link" and child.get("type") == "application/x-zim":
                href = child.get("href", "")
                d["url"] = href[:-6] if href.endswith(".meta4") else href
                d["size"] = int(child.get("length") or 0)
        if d["url"]:
            d["filename"] = d["url"].rsplit("/", 1)[-1]
            entries.append(d)
    return entries


def _pick(entries: list[dict], name: str = "", flavour: str = "", query: str = "") -> dict | None:
    if name:
        entries = [e for e in entries if e["name"] == name] or entries
    if flavour:
        flav = [e for e in entries if e["flavour"] == flavour]
        if flav:
            entries = flav
    if not entries:
        return None
    if query and not name:
        words = [w for w in re.findall(r"[a-z0-9.]+", query.lower()) if len(w) > 2]
        score = lambda e: sum(w in (e["title"] + " " + e["name"]).lower() for w in words)
        entries = sorted(entries, key=score, reverse=True)
        best = score(entries[0])
        entries = [e for e in entries if score(e) == best]
    return max(entries, key=lambda e: e["updated"])


class KiwixCatalog:
    def __init__(self, cache_path: str, http=requests):
        self.http, self.cache_path = http, Path(cache_path)
        try:
            self.cache = json.loads(self.cache_path.read_text())
        except Exception:
            self.cache = {}

    def _fetch(self, **params) -> list[dict]:
        r = self.http.get(OPDS, params={"count": 60, **params}, headers=UA, timeout=20)
        r.raise_for_status()
        return parse_opds(r.text)

    def search(self, q: str) -> list[dict]:
        return self._fetch(q=q, lang="eng")[:30]

    def resolve(self, item: dict, refresh: bool = False) -> dict | None:
        key = item["id"]
        hit = self.cache.get(key)
        if hit and not refresh and time.time() - hit.get("_at", 0) < 7 * 86400:
            return hit
        found = None
        if item.get("name"):
            found = _pick(self._fetch(name=item["name"]), item["name"], item.get("flavour", ""))
        if not found and item.get("query"):
            found = _pick(self._fetch(q=item["query"], lang="eng"), "", item.get("flavour", ""),
                          item["query"])
        if found:
            found["_at"] = time.time()
            self.cache[key] = found
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1))
        return found


# ------------------------------------------------------------------ install state

class Installed:
    """Remembers which catalog item produced which file. Paths are stored relative to the
    drive's Beacon folder so the record stays valid on both macOS and Windows."""
    def __init__(self, path: str, root: str | None = None):
        self.path, self.root = Path(path), Path(root) if root else None
        try:
            self.map = json.loads(self.path.read_text())
        except Exception:
            self.map = {}

    def _rel(self, file: str) -> str:
        p = Path(file)
        if self.root:
            try:
                return p.relative_to(self.root).as_posix()
            except ValueError:
                pass
        return str(p)

    def _abs(self, stored: str) -> Path:
        p = Path(stored)
        return p if p.is_absolute() or not self.root else self.root / p

    def set(self, item_id: str, file: str):
        self.map[item_id] = self._rel(file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.map, indent=1))

    def stored(self, item_id: str) -> str | None:
        f = self.map.get(item_id)
        return str(self._abs(f)) if f else None

    def file_for(self, item_id: str) -> str | None:
        f = self.stored(item_id)
        return f if f and Path(f).exists() else None


def destination(item: dict, cfg: dict, resolved: dict | None = None) -> Path:
    if item["type"] == "zim":
        return Path(cfg["zim_dir"]) / (resolved or {}).get("filename", f"{item['id']}.zim")
    if item.get("shelf"):  # reading shelf: kept out of the search index
        return Path(cfg.get("books_dir") or Path(cfg["manuals_dir"]).parent / "books") / item["band"] / item["file"]
    return Path(cfg["manuals_dir"]) / item["band"] / item["file"]


def free_bytes(path: str) -> int:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def is_online(http=requests) -> bool:
    try:
        return http.head("https://library.kiwix.org", headers=UA, timeout=4).status_code < 500
    except requests.RequestException:
        return False


# ------------------------------------------------------------------ downloads

class Downloader:
    """One background worker, resumable downloads, progress you can poll."""
    def __init__(self, installed: Installed, on_done=None, http=requests):
        self.installed, self.on_done, self.http = installed, on_done, http
        self.jobs: dict[str, dict] = {}
        self.queue: list[str] = []
        self.lock = threading.Lock()
        self.worker = None

    def add(self, item: dict, url: str, dest: Path, size: int = 0):
        with self.lock:
            job = self.jobs.get(item["id"])
            if job and job["state"] in ("queued", "downloading"):
                return
            self.jobs[item["id"]] = {"id": item["id"], "title": item["title"], "type": item["type"],
                                     "url": url, "dest": str(dest), "total": size, "done": 0,
                                     "state": "queued", "error": ""}
            self.queue.append(item["id"])
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()

    def add_task(self, item_id: str, title: str, fn, kind: str = "task"):
        """Queue custom work (map building, model download). fn(job) updates job['detail'],
        job['done'] and job['total'] as it goes."""
        with self.lock:
            job = self.jobs.get(item_id)
            if job and job["state"] in ("queued", "downloading"):
                return
            self.jobs[item_id] = {"id": item_id, "title": title, "type": kind, "fn": fn,
                                  "total": 0, "done": 0, "state": "queued", "error": "",
                                  "detail": ""}
            self.queue.append(item_id)
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()

    def cancel(self, item_id: str):
        with self.lock:
            job = self.jobs.get(item_id)
            if job and job["state"] in ("queued", "downloading"):
                job["state"] = "cancelled"

    def status(self) -> list[dict]:
        return [{k: v for k, v in j.items() if k != "fn"} for j in self.jobs.values()]

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                job = self.jobs[self.queue.pop(0)]
            if job["state"] == "cancelled":
                continue
            try:
                if job.get("fn"):
                    job["state"] = "downloading"
                    job["fn"](job)
                    if job["state"] not in ("cancelled", "done"):
                        job["state"] = "done"
                        if self.on_done:
                            self.on_done(job)
                else:
                    self._download(job)
            except Exception as e:  # network drop, disk full, 404...
                job["state"], job["error"] = "failed", str(e)[:200]

    def _download(self, job: dict):
        dest = Path(job["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = dict(UA)
        if have:
            headers["Range"] = f"bytes={have}-"
        job["state"] = "downloading"
        with self.http.get(job["url"], headers=headers, stream=True, timeout=30,
                           allow_redirects=True) as r:
            if r.status_code == 416:  # already complete
                pass
            else:
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range: start over
                    have = 0
                length = int(r.headers.get("Content-Length") or 0)
                if length:
                    job["total"] = have + length
                need = (job["total"] or 0) - have
                if need > 0 and need > free_bytes(str(dest.parent)) - 200 * 1024 ** 2:
                    raise OSError("Not enough free space on the drive")
                job["done"] = have
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if job["state"] == "cancelled":
                            return
                        f.write(chunk)
                        job["done"] += len(chunk)
        part.replace(dest)
        old = self.installed.stored(job["id"])
        if old and Path(old) != dest and Path(old).exists():  # replace an older edition
            Path(old).unlink()
        job["state"] = "done"
        self.installed.set(job["id"], str(dest))
        if self.on_done:
            self.on_done(job)
