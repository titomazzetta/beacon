"""Security log: who signed in over the Wi-Fi, who tried and failed, and what Beacon blocked.

Events are kept in memory for the Connections panel and appended to data/logs/security.log
(one JSON object per line). Only security events are logged: never questions, answers or
searches. Warnings and alerts also raise a macOS notification, so the person running Beacon
hears about them even when the browser is hidden.
"""
import csv
import io
import json
import platform
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

LEVELS = ("info", "warn", "alert")
COALESCE = 60          # identical events from one device within this many seconds are counted, not repeated
NOTIFY_EVERY = 20      # at most one desktop notification this often
MAX_BYTES = 1024 * 1024
FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    """Spreadsheet apps treat a cell starting with = + - or @ as a formula. Log fields can carry
    text someone else chose (a host name, a browser name), so such cells get a leading apostrophe."""
    s = str(value)
    return "'" + s if s.startswith(FORMULA) else s


def describe(ua: str | None) -> str:
    """'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 ...) ... Safari/604.1' -> 'iPhone, Safari'."""
    ua = ua or ""
    if not ua:
        return "Unknown device"
    m = re.match(r"Beacon-link/\d+ \(([^)]*)\)", ua)
    if m:
        return f"Linked Beacon ({m.group(1) or 'unnamed'})"
    if "iPhone" in ua:
        device = "iPhone"
    elif "iPad" in ua:
        device = "iPad"
    elif "Android" in ua:
        device = "Android phone" if "Mobile" in ua else "Android tablet"
    elif "CrOS" in ua:
        device = "Chromebook"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        device = "Mac"
    elif "Windows" in ua:
        device = "Windows PC"
    elif "Linux" in ua:
        device = "Linux computer"
    elif re.search(r"curl|wget|python|go-http|java|okhttp|libwww|scan|nmap|nikto|sqlmap", ua, re.I):
        return f"Script or tool ({ua.split('/')[0][:30]})"
    else:
        device = "Unknown device"
    for pat, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
                      ("FxiOS", "Firefox"), ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"),
                      ("Safari/", "Safari")):
        if pat in ua:
            return f"{device}, {name}"
    return device


def hardware_address(ip: str) -> str | None:
    """The device's Wi-Fi hardware (MAC) address from the Mac's own address table. Phones often
    use a private address per network, which still stays the same on this Wi-Fi."""
    if not ip or not shutil.which("arp"):
        return None
    try:
        out = subprocess.run(["arp", "-n", ip], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"\b([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b", out, re.I)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def nearby_devices() -> list[dict]:
    """Devices this Mac has recently exchanged traffic with on the local network, read from its
    address table. Nothing is sent: this never probes or scans other devices."""
    if not shutil.which("arp"):
        return []
    try:
        out = subprocess.run(["arp", "-a", "-n"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    seen = []
    for line in out.splitlines():
        m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+|\(incomplete\))", line, re.I)
        if not m or m.group(2).startswith("(") or m.group(2) in ("ff:ff:ff:ff:ff:ff",):
            continue
        ip = m.group(1)
        if ip.startswith(("224.", "239.", "255.")) or ip.endswith(".255"):
            continue
        seen.append({"ip": ip, "mac": m.group(2).lower()})
    return seen


def _applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mac_notify(title: str, message: str):
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        return
    script = f"display notification {_applescript_string(message)} with title {_applescript_string(title)} sound name \"Basso\""
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class Audit:
    def __init__(self, path: str | None, notify=mac_notify, keep: int = 500):
        self.path = Path(path) if path else None
        self.notify = notify
        self.events: deque[dict] = deque(maxlen=keep)
        self.lock = threading.Lock()
        self.seq = 0
        self.unseen = 0
        self.last_notified = 0.0
        self.macs: dict[str, str | None] = {}
        self._load()

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            lines = self.path.read_text(errors="ignore").splitlines()[-self.events.maxlen:]
            for line in lines:
                ev = json.loads(line)
                self.seq = max(self.seq, int(ev.get("id", 0)))
                self.events.append(ev)
        except Exception:
            pass

    def mac_for(self, ip: str) -> str | None:
        if ip not in self.macs:
            self.macs[ip] = hardware_address(ip)
        return self.macs[ip]

    def add(self, kind: str, ip: str, ua: str = "", detail: str = "", level: str = "info") -> dict:
        now, device = time.time(), describe(ua)
        with self.lock:
            for ev in reversed(self.events):  # the same thing again from the same device: count it
                if now - ev["last"] > COALESCE:
                    break
                if ev["kind"] == kind and ev["ip"] == ip and ev["device"] == device and ev["detail"] == detail:
                    ev["count"] += 1
                    ev["last"] = now
                    return ev
            self.seq += 1
            ev = {"id": self.seq, "t": now, "last": now, "kind": kind, "level": level, "ip": ip,
                  "device": device, "mac": None, "detail": detail, "count": 1}
            self.events.append(ev)
            if level != "info":
                self.unseen += 1
        if ip not in ("127.0.0.1", "::1"):
            ev["mac"] = self.mac_for(ip)
        self._write(ev)
        if level != "info" and self.notify and now - self.last_notified > NOTIFY_EVERY:
            self.last_notified = now
            who = f"{ev['device']} at {ip}" if ip not in ("127.0.0.1", "::1") else "a web page on this Mac"
            try:
                self.notify("Beacon security", f"{detail} ({who})")
            except Exception:
                pass
        return ev

    def _write(self, ev: dict):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:  # keep the newest half
                lines = self.path.read_text(errors="ignore").splitlines()
                self.path.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except OSError:
            pass

    def since(self, after: int = 0, limit: int = 100) -> list[dict]:
        with self.lock:
            return [dict(e) for e in self.events if e["id"] > after][-limit:]

    def mark_seen(self):
        self.unseen = 0

    def failures_since(self, seconds: float) -> int:
        cutoff = time.time() - seconds
        return sum(e["count"] for e in self.events if e["level"] != "info" and e["last"] >= cutoff)

    def csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["time", "level", "event", "device", "ip", "hardware_address", "times", "detail"])
        for e in list(self.events):
            w.writerow([_cell(x) for x in (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["t"])), e["level"],
                                           e["kind"], e["device"], e["ip"], e.get("mac") or "", e["count"], e["detail"])])
        return buf.getvalue()
