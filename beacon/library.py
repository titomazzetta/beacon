"""Library Manager: catalog of bands/tiers, live Kiwix lookups, resumable downloads."""
import hashlib
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


def items_for_tier(catalog: dict, tier: str, bands: list[str] | None = None,
                   optional: bool = False) -> list[dict]:
    """Downloadable items up to and including `tier`. Optional items (e.g. Wikipedia with
    images) are only chosen when asked for, and only one item per exclusive group is chosen:
    the largest tier that qualifies (optional items count as the largest)."""
    limit = TIER_ORDER.index(tier)
    chosen, groups = [], {}
    for it in all_items(catalog):
        if it["type"] == "link" or (it.get("optional") and not optional):
            continue
        if bands and it["band"] not in bands:
            continue
        if TIER_ORDER.index(it["tier"]) > limit:
            continue
        g = it.get("group")
        if g:
            prev = groups.get(g)
            rank = lambda x: (TIER_ORDER.index(x["tier"]), bool(x.get("optional")))
            if prev is None or rank(it) >= rank(prev):
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
        self._save()

    def forget(self, item_id: str):
        if self.map.pop(item_id, None) is not None:
            self._save()

    def _save(self):
        try:  # another process (the builder, or Beacon itself) may have written since we loaded
            on_disk = json.loads(self.path.read_text())
        except Exception:
            on_disk = {}
        on_disk.update(self.map)
        self.map = on_disk
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.map, indent=1))

    def stored(self, item_id: str) -> str | None:
        f = self.map.get(item_id)
        return str(self._abs(f)) if f else None

    def file_for(self, item_id: str) -> str | None:
        f = self.stored(item_id)
        return f if f and Path(f).exists() else None


class Integrity:
    """The SHA-256 fingerprint of every downloaded file, so later corruption or tampering
    shows up in the health check. Paths are relative to the drive's Beacon folder."""
    def __init__(self, path: str, root: str | None = None):
        self.path, self.root = Path(path), Path(root) if root else None
        self.lock = threading.Lock()
        try:
            self.map = json.loads(self.path.read_text())
        except Exception:
            self.map = {}

    def _rel(self, file) -> str:
        p = Path(file)
        if self.root:
            try:
                return p.relative_to(self.root).as_posix()
            except ValueError:
                pass
        return str(p)

    def record(self, file, digest: str, source: str = "", publisher_checked: bool = False):
        with self.lock:
            self.map[self._rel(file)] = {"sha256": digest, "source": source,
                                         "publisher_checked": publisher_checked, "at": int(time.time())}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.map, indent=1))

    def forget(self, file):
        with self.lock:
            if self.map.pop(self._rel(file), None) is not None:
                self.path.write_text(json.dumps(self.map, indent=1))

    def verify(self, max_bytes: int = 1024 ** 3) -> list[dict]:
        """Re-hash recorded files (big ones are skipped: they were checked when downloaded)."""
        out = []
        for rel, meta in sorted(self.map.items()):
            p = Path(rel) if Path(rel).is_absolute() or not self.root else self.root / rel
            if not p.exists():
                continue  # removed on purpose, or replaced by a newer edition
            if p.stat().st_size > max_bytes:
                out.append({"file": rel, "ok": True, "skipped": True})
                continue
            out.append({"file": rel, "ok": sha256_file(p) == meta["sha256"], "skipped": False})
        return out


_EDITION = re.compile(r"_(\d{4}-\d{2})\.zim$")


def file_problem(path, suffix: str | None = None) -> str | None:
    """Why a downloaded file can't be used, or None. Sites that block automatic downloads
    often answer 200 OK with an empty body or an HTML page; neither is the manual."""
    p = Path(path)
    suffix = (suffix or p.suffix).lower()
    try:
        size = p.stat().st_size
    except OSError:
        return "The file is missing."
    if size == 0:
        return "The site sent an empty file. Try again later, or open the link in a browser and save the file into Beacon/library/manuals."
    with open(p, "rb") as f:
        head = f.read(64)
    if suffix == ".pdf" and not head.startswith(b"%PDF"):
        return ("The site sent a web page instead of the PDF; some publishers block automatic downloads. "
                "Open the link in a browser and save the file into Beacon/library/manuals.")
    if suffix in (".txt", ".md") and head.lstrip().lower().startswith((b"<!doctype", b"<html")):
        return "The site sent a web page instead of the text. Open the link in a browser and save it into Beacon/library."
    return None


def older_editions(path) -> list[Path]:
    """Other dated editions of the same Kiwix file next to this one (diy..._2026-08.zim beside 2026-10)."""
    p = Path(path)
    m = _EDITION.search(p.name)
    if not m:
        return []
    stem = p.name[:m.start()]
    out = []
    for other in p.parent.glob(stem + "_*.zim"):
        m2 = _EDITION.search(other.name)
        if other != p and m2 and other.name[:m2.start()] == stem and m2.group(1) <= m.group(1):
            out.append(other)
    return out


def leftovers(zim_dir: str, installed: "Installed", catalog: dict | None = None) -> list[dict]:
    """Files on the drive that Beacon no longer needs: editions superseded by a newer download,
    and group members (Wikipedia intros) made redundant by a fuller one. Reported, never deleted."""
    recorded = {}
    for item_id, rel in installed.map.items():
        recorded[str(Path(installed._abs(rel)).resolve())] = item_id
    out = []
    for f in sorted(Path(zim_dir).glob("*.zim")):
        if str(f.resolve()) in recorded:
            continue
        newer = [o for o in Path(zim_dir).glob("*.zim") if f in older_editions(o)]
        why = f"An older edition of {newer[0].name}" if newer else "Not in the install records"
        out.append({"file": f.name, "gb": round(f.stat().st_size / 1e9, 1), "why": why})
    if catalog:
        by_group: dict[str, list[dict]] = {}
        for it in all_items(catalog):
            if it.get("group") and installed.file_for(it["id"]):
                by_group.setdefault(it["group"], []).append(it)
        for members in by_group.values():
            members.sort(key=lambda it: TIER_ORDER.index(it["tier"]))
            best = members[-1]
            for it in members[:-1]:
                f = Path(installed.file_for(it["id"]))
                out.append({"file": f.name, "gb": round(f.stat().st_size / 1e9, 1),
                            "why": f"Replaced by {best['title']}", "item": it["id"]})
    return out


def sha256_file(path, h=None) -> str:
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def destination(item: dict, cfg: dict, resolved: dict | None = None) -> Path:
    if item["type"] == "zim":
        return Path(cfg["zim_dir"]) / (resolved or {}).get("filename", f"{item['id']}.zim")
    if item.get("files"):  # several files that belong together get their own folder
        return Path(cfg["manuals_dir"]) / item["band"] / item["id"]
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
    def __init__(self, installed: Installed, on_done=None, http=requests, integrity: Integrity | None = None):
        self.installed, self.on_done, self.http, self.integrity = installed, on_done, http, integrity
        self.jobs: dict[str, dict] = {}
        self.queue: list[str] = []
        self.lock = threading.Lock()
        self.worker = None

    def add(self, item: dict, url: str, dest: Path, size: int = 0, sha256_url: str | None = None):
        with self.lock:
            job = self.jobs.get(item["id"])
            if job and job["state"] in ("queued", "downloading"):
                return
            self.jobs[item["id"]] = {"id": item["id"], "title": item["title"], "type": item["type"],
                                     "url": url, "dest": str(dest), "total": size, "done": 0,
                                     "state": "queued", "error": "", "sha256_url": sha256_url}
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

    def _publisher_sha256(self, job: dict) -> str | None:
        """The checksum the publisher lists next to the file (Kiwix does), if any."""
        url = job.get("sha256_url")
        if not url:
            return None
        try:
            r = self.http.get(url, headers=UA, timeout=20)
            if r.status_code != 200:
                return None
            m = re.search(r"\b[0-9a-fA-F]{64}\b", r.text or "")
            return m.group(0).lower() if m else None
        except Exception:
            return None

    def _download(self, job: dict, record: bool = True):
        dest = Path(job["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = dict(UA)
        if have:
            headers["Range"] = f"bytes={have}-"
        job["state"] = "downloading"
        h = hashlib.sha256()  # fingerprint the file as it arrives: no second read of big files
        with self.http.get(job["url"], headers=headers, stream=True, timeout=30,
                           allow_redirects=True) as r:
            if r.status_code == 416:  # already complete
                sha256_file(part, h)
            else:
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range: start over
                    have = 0
                if have:
                    sha256_file(part, h)
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
                        h.update(chunk)
                        job["done"] += len(chunk)
        digest = h.hexdigest()
        expected = self._publisher_sha256(job)
        if expected and expected != digest:
            part.unlink(missing_ok=True)
            raise ValueError("The download didn't match the publisher's checksum, so Beacon deleted it. Try again.")
        problem = file_problem(part, dest.suffix)
        if problem:  # an empty body, or a web page where a PDF should be: never keep it
            part.unlink(missing_ok=True)
            raise ValueError(problem)
        part.replace(dest)
        job["sha256"], job["verified"] = digest, bool(expected)
        if self.integrity:
            self.integrity.record(dest, digest, job.get("url", ""), bool(expected))
        for old in older_editions(dest):  # the same Kiwix file, earlier date: superseded
            old.unlink()
            if self.integrity:
                self.integrity.forget(old)
        if not record:  # one file of a multi-file item; the caller records the whole item
            return
        old = self.installed.stored(job["id"])
        if old and Path(old) != dest and Path(old).exists():  # replace an older edition
            Path(old).unlink()
            if self.integrity:
                self.integrity.forget(old)
        job["state"] = "done"
        self.installed.set(job["id"], str(dest))
        if self.on_done:
            self.on_done(job)


def queue_item(it: dict, downloader: "Downloader", kcat: KiwixCatalog, cfg: dict, http=requests):
    """Queue one catalog item for download, whatever its kind. Used by the app and the drive builder."""
    if it["type"] == "zim":
        def task(job, it=it):  # look up the newest edition in the background, then download
            r = kcat.resolve(it)
            if not r:
                raise LookupError("not found in the Kiwix catalog")
            job.update(url=r["url"], dest=str(destination(it, cfg, r)), total=r["size"],
                       sha256_url=r["url"] + ".sha256")  # Kiwix publishes a checksum for every file
            downloader._download(job)
        downloader.add_task(it["id"], it["title"], task, "zim")
    elif it.get("files"):  # several PDFs that belong together (e.g. the USDA canning guide)
        def task(job, it=it):
            folder = destination(it, cfg)
            job["total"] = len(it["files"])
            for n, f in enumerate(it["files"], 1):
                job["detail"] = f"{n}/{len(it['files'])}: {f['file']}"
                sub = {"id": f"{it['id']}#{n}", "title": f["file"], "state": "downloading",
                       "url": f["url"], "dest": str(folder / f["file"]), "total": 0, "done": 0}
                downloader._download(sub, record=False)
                job["done"] = n
            downloader.installed.set(it["id"], str(folder))
        downloader.add_task(it["id"], it["title"], task, "pdf")
    elif it["type"] == "page":  # a web page saved as plain text
        def task(job, it=it):
            from .kiwix_source import html_to_text
            r = http.get(it["url"], headers=UA, timeout=60)
            r.raise_for_status()
            dest = destination(it, cfg)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f"# {it['title']}\n\nSource: {it['url']}\nSaved: {time.strftime('%Y-%m-%d')}\n\n"
                            + html_to_text(r.text), encoding="utf-8")
            downloader.installed.set(it["id"], str(dest))
            if downloader.integrity:
                downloader.integrity.record(dest, sha256_file(dest), it["url"])
        downloader.add_task(it["id"], it["title"], task, "page")
    elif it["type"] in ("pdf", "text"):
        downloader.add({**it}, it["url"], destination(it, cfg))
