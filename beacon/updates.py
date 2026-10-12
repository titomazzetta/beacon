"""Updates from outside: official alerts, disasters and headlines, fetched only when this Mac is
online and the person running Beacon has turned updates on.

Everything fetched is cached on the drive, so it can still be read offline, by phones on the
Wi-Fi, and by the AI (as dated context it's told may be out of date). Feeds are listed in
catalog.json under "updates", so adding a source is one entry there.

What leaves the Mac: requests to the feeds below. The National Weather Service gets the rough
coordinates of the place in your setup (rounded to about a kilometer); nothing else is sent.
"""
import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .kiwix_source import html_to_text

# The weather service asks every app to name itself; this names the app, never the person or the Mac.
UA = {"User-Agent": "Beacon/1.0 (offline survival guide; updates)", "Accept": "application/geo+json, application/json, application/xml, text/xml, */*"}
MAX_BYTES = 2 * 1024 * 1024     # no feed needs more; a bigger answer is cut off
MAX_ITEMS = 80
STALE = 30 * 60                 # automatic checks at most every 30 minutes
LEVELS = {"alert": 0, "warn": 1, "info": 2}
SCOPES = {"local": 0, "world": 1, "news": 2}


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _text(s, n: int = 400) -> str:
    s = html_to_text(str(s or "")) if "<" in str(s or "") else str(s or "")
    return re.sub(r"\s+", " ", s).strip()[:n]


def _link(u) -> str:
    u = str(u or "").strip()
    return u if re.match(r"^https?://", u) else ""


def _when(s) -> float:
    if not s:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s) / (1000 if s > 1e11 else 1)
    try:
        return parsedate_to_datetime(s).timestamp()          # RSS dates
    except Exception:
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()  # ISO dates
    except Exception:
        return 0.0


def _get(http, url: str):
    """Fetch with a size cap. Returns (content type, bytes)."""
    with http.get(url, headers=UA, timeout=15, stream=True) as r:
        r.raise_for_status()
        body = b""
        for chunk in r.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        return r.headers.get("Content-Type", ""), body[:MAX_BYTES]


def _xml(body: bytes):
    if re.search(rb"<!(DOCTYPE|ENTITY)", body, re.I):     # feeds never need these; refusing them avoids XML bombs
        raise ValueError("feed has a document type declaration")
    return ET.fromstring(body)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def _child(el, name: str) -> str:
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip() or c.attrib.get("href", "")
    return ""


# ---------------------------------------------------------------- parsers, one per kind of feed

def parse_nws(body: bytes, feed: dict) -> list[dict]:
    out = []
    for f in json.loads(body).get("features", []):
        p = f.get("properties") or {}
        sev = p.get("severity", "")
        out.append({"title": _text(p.get("headline") or p.get("event"), 200), "event": _text(p.get("event"), 80),
                    "summary": _text(p.get("description"), 600), "instruction": _text(p.get("instruction"), 400),
                    "area": _text(p.get("areaDesc"), 160), "url": _link(p.get("@id") or p.get("id")),
                    "time": _when(p.get("effective") or p.get("sent")), "expires": _when(p.get("expires") or p.get("ends")),
                    "level": "alert" if sev in ("Extreme", "Severe") else "warn" if sev == "Moderate" else "info"})
    return out


def parse_usgs(body: bytes, feed: dict) -> list[dict]:
    out = []
    for f in json.loads(body).get("features", []):
        p = f.get("properties") or {}
        alert = p.get("alert") or ""
        out.append({"title": _text(p.get("title"), 200), "summary": "Tsunami possible: check official warnings." if p.get("tsunami") else "",
                    "area": _text(p.get("place"), 160), "url": _link(p.get("url")), "time": _when(p.get("time")),
                    "level": "alert" if alert in ("red", "orange") else "warn" if alert == "yellow" else "info"})
    return out


def parse_rss(body: bytes, feed: dict) -> list[dict]:
    root = _xml(body)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = _text(_child(el, "title"), 200)
        if not title:
            continue
        level = "info"
        alert = _child(el, "alertlevel").lower()           # GDACS
        if alert:
            level = "alert" if alert == "red" else "warn" if alert == "orange" else "info"
        m = re.search(r"Level (\d)", title)                  # US State Department travel advisories
        if m and feed.get("id") == "travel":
            level = "alert" if m.group(1) == "4" else "warn" if m.group(1) == "3" else "info"
        out.append({"title": title, "summary": _text(_child(el, "description") or _child(el, "summary"), 400),
                    "area": _text(_child(el, "country"), 120), "url": _link(_child(el, "link")),
                    "time": _when(_child(el, "pubdate") or _child(el, "updated") or _child(el, "published")),
                    "level": level})
    return out


PARSERS = {"nws": parse_nws, "usgs": parse_usgs, "rss": parse_rss}


class Updates:
    def __init__(self, path: str, feeds: list[dict], http=requests):
        self.path, self.feeds, self.http = Path(path), feeds, http
        self.lock = threading.Lock()
        self.checking = False
        self.state = {"auto": False, "checked": 0, "items": [], "errors": {}, "place": ""}
        try:
            self.state.update(json.loads(self.path.read_text()))
        except Exception:
            pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.path)

    def set_auto(self, on: bool):
        with self.lock:
            self.state["auto"] = bool(on)
            self._save()

    def due(self) -> bool:
        return self.state["auto"] and not self.checking and time.time() - self.state["checked"] > STALE

    def refresh(self, where: dict | None = None) -> dict:
        """Fetch every feed. where: {"lat", "lon", "cc", "label"} for local alerts (US only for now)."""
        self.checking = True
        items, errors = [], {}
        try:
            for feed in self.feeds:
                url = feed["url"]
                if "{lat}" in url:
                    if not where or (feed.get("country") and where.get("cc") != feed["country"]):
                        continue
                    url = url.format(lat=round(where["lat"], 2), lon=round(where["lon"], 2))
                try:
                    _, body = _get(self.http, url)
                    found = PARSERS[feed["kind"]](body, feed)
                except Exception as e:
                    errors[feed["id"]] = (str(e) or e.__class__.__name__)[:160]
                    continue
                for it in found[: feed.get("max", 15)]:
                    it.update(feed=feed["id"], source=feed["title"], scope=feed.get("scope", "news"),
                              id=_id(feed["id"], it["title"], it.get("time")))
                    items.append(it)
            now = time.time()
            items = [i for i in items if not i.get("expires") or i["expires"] > now]
            items.sort(key=lambda i: (SCOPES.get(i["scope"], 3), LEVELS.get(i["level"], 3), -(i.get("time") or 0)))
            with self.lock:
                self.state.update(checked=now, items=items[:MAX_ITEMS], errors=errors,
                                  place=(where or {}).get("label", ""))
                self._save()
        finally:
            self.checking = False
        return self.view()

    def view(self) -> dict:
        return {**self.state, "checking": self.checking,
                "feeds": [{"id": f["id"], "title": f["title"], "scope": f.get("scope", "news")} for f in self.feeds]}

    def context(self, max_age: float = 36 * 3600) -> str:
        """Dated notes for the AI: local alerts, serious world events and a few headlines."""
        st = self.state
        if not st["items"] or time.time() - st["checked"] > max_age:
            return ""
        local = [i for i in st["items"] if i["scope"] == "local"][:4]
        world = [i for i in st["items"] if i["scope"] == "world" and i["level"] != "info"][:3]
        news = [i for i in st["items"] if i["scope"] == "news"][:3]
        lines = []
        for i in local + world + news:
            extra = f" ({i['area']})" if i.get("area") else ""
            lines.append(f"- {i['source']}: {i['title']}{extra}")
        if not lines:
            return ""
        when = time.strftime("%b %d, %I:%M %p", time.localtime(st["checked"]))
        return f"CURRENT UPDATES (fetched {when}; may be incomplete or out of date):\n" + "\n".join(lines)
