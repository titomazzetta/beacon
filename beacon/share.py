"""Share Beacon with phones and other computers on the same Wi-Fi.

When sharing is on, a second web server listens on the local network (port 80 if the Mac
allows it, so people can type just "beacon.local"; otherwise 8643). Guests enter a 4-digit
code once (or scan the QR code that includes it) and get a random session token in a cookie.
Wrong codes are rate limited per device, and the code changes by itself if someone keeps
guessing. Stopping sharing signs every guest out.
"""
import ipaddress
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time

from werkzeug.serving import make_server

LOCAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
MAX_TRIES = 5          # wrong codes allowed from one device...
WINDOW = 300           # ...within this many seconds
ROTATE_AFTER = 25      # wrong codes from everyone before the code changes by itself


def is_local(addr: str | None) -> bool:
    return (addr or "") in LOCAL


def host_name(host: str) -> str:
    """'beacon.local:8643' -> 'beacon.local'; '[::1]:8642' -> '::1'."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def allowed_host(host: str) -> bool:
    """Only answer to Beacon's own names. This blocks DNS rebinding: a web page on some
    other domain can't point that domain at this Mac and read Beacon's answers."""
    name = host_name(host)
    if name in ("localhost", "beacon.local"):
        return True
    try:
        ipaddress.ip_address(name)    # a bare IP address can't be rebound
        return True
    except ValueError:
        pass
    return name.endswith(".local")    # Bonjour names only resolve on the local network


def lan_ip() -> str | None:
    """The Mac's address on the local network (Wi-Fi first, then wired)."""
    if shutil.which("ipconfig"):
        for iface in ("en0", "en1", "en2"):
            try:
                ip = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True, timeout=3).strip()
                if ip:
                    return ip
            except Exception:
                continue
    try:  # works on any OS; no packet is actually sent
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        if not ipaddress.ip_address(ip).is_loopback:
            return ip
    except Exception:
        pass
    return None


def _port_problem(port: int) -> str:
    """'' if we can listen on this port, else a short reason. (Werkzeug exits the whole
    process when a port is taken, so check first.)"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("0.0.0.0", port))
        return ""
    except OSError as e:
        return f"port {port} is unavailable ({e.strerror or e})"
    finally:
        probe.close()


class Share:
    def __init__(self, app, ports=(80, 8643)):
        self.app, self.ports = app, ports
        self.server = self.thread = self.mdns = self.awake = None
        self.port = self.code = self.ip = None
        self.error = ""
        self.alert = ""
        self.tokens: dict[str, dict] = {}
        self.failures: dict[str, list[float]] = {}
        self.fail_total = 0
        self.lock = threading.Lock()

    @property
    def on(self) -> bool:
        return self.server is not None

    # ------------------------------------------------------------ guests
    def check_code(self, ip: str, code: str) -> tuple[bool, str, str]:
        """Is this the right code? Rate limited per device, and the code rotates if many
        wrong codes come in, so the 10,000 combinations can't simply be tried one by one.
        Returns (ok, message for the person, event for the security log)."""
        now = time.time()
        with self.lock:
            tries = [t for t in self.failures.get(ip, []) if now - t < WINDOW]
            self.failures[ip] = tries
            if len(tries) >= MAX_TRIES:
                mins = max(1, round((WINDOW - (now - tries[0])) / 60))
                return False, f"Too many wrong codes from this device. Try again in {mins} minute{'s' if mins > 1 else ''}.", "still-locked"
            if self.on and self.code and secrets.compare_digest(str(code).encode(), self.code.encode()):
                self.failures.pop(ip, None)
                return True, "", "ok"
            tries.append(now)
            self.fail_total += 1
            event = "locked" if len(tries) >= MAX_TRIES else "wrong"
            if self.on and self.fail_total >= ROTATE_AFTER:
                self.code = self._new_code()
                self.fail_total = 0
                self.alert = "Someone entered a lot of wrong codes, so Beacon changed the code."
                event = "rotated"
            return False, "That code didn't match. Check the Beacon screen.", event

    def new_token(self, ip: str, ua: str = "") -> str:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with self.lock:
            self.tokens[token] = {"id": secrets.token_hex(4), "ip": ip, "ua": ua[:300], "since": now, "last": now, "hits": 0}
        return token

    def valid(self, token: str | None) -> bool:
        return bool(self.on and token and token in self.tokens)

    def touch(self, token: str, ip: str, ua: str = ""):
        s = self.tokens.get(token)
        if s:
            s["last"], s["ip"], s["hits"] = time.time(), ip, s["hits"] + 1
            if ua:
                s["ua"] = ua[:300]

    def revoke(self, sid: str) -> dict | None:
        """Sign out one device."""
        with self.lock:
            for token, s in list(self.tokens.items()):
                if s["id"] == sid:
                    return self.tokens.pop(token)
        return None

    def sessions(self) -> list[dict]:
        now = time.time()
        return [{"id": s["id"], "ip": s["ip"], "ua": s["ua"], "since": s["since"], "last": s["last"],
                 "hits": s["hits"], "active": now - s["last"] < 120} for s in self.tokens.values()]

    def sign_out_all(self) -> dict:
        """A new code, and every phone has to join again."""
        with self.lock:
            self.tokens.clear()
            self.failures.clear()
            self.fail_total = 0
            self.alert = ""
            if self.on:
                self.code = self._new_code()
        return self.status()

    @staticmethod
    def _new_code() -> str:
        return f"{secrets.randbelow(10000):04d}"

    # ------------------------------------------------------------ server
    def start(self) -> dict:
        if self.on:
            return self.status()
        self.error = ""
        for port in self.ports:
            problem = _port_problem(port)
            if problem:
                self.error = problem
                continue
            try:
                self.server = make_server("0.0.0.0", port, self.app, threaded=True)
                self.port = self.server.server_port
                break
            except (OSError, SystemExit) as e:
                self.server, self.error = None, f"port {port} is unavailable ({e})"
        if not self.server:
            return self.status()
        self.error = ""
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.code = self._new_code()
        self.ip = lan_ip()
        if self.ip and shutil.which("dns-sd"):
            # Bonjour: makes http://beacon.local work on iPhones, iPads, Macs and most Androids.
            try:
                self.mdns = subprocess.Popen(
                    ["dns-sd", "-P", "Beacon", "_http._tcp", "local", str(self.port), "beacon.local", self.ip],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                self.mdns = None
        if shutil.which("caffeinate"):
            # Phones lose Beacon if the Mac dozes off, so keep it awake while sharing.
            # (-i: no idle sleep; -s: no system sleep on power. -w: ends with Beacon.)
            try:
                self.awake = subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                self.awake = None
        return self.status()

    def stop(self) -> dict:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        for proc in (self.mdns, self.awake):
            if proc:
                proc.terminate()
        self.server = self.thread = self.mdns = self.awake = None
        self.port = self.code = None
        with self.lock:
            self.tokens.clear()
            self.failures.clear()
            self.fail_total = 0
            self.alert = ""
        return self.status()

    def status(self) -> dict:
        if not self.on:
            return {"on": False, "error": self.error}
        port = "" if self.port == 80 else f":{self.port}"
        name_url = f"http://beacon.local{port}"
        ip_url = f"http://{self.ip}{port}" if self.ip else None
        return {"on": True, "port": self.port, "code": self.code, "ip": self.ip,
                "name_url": name_url if self.mdns else None, "ip_url": ip_url,
                "join_url": f"{ip_url or name_url}/?code={self.code}",
                "guests": len(self.tokens), "alert": self.alert}
