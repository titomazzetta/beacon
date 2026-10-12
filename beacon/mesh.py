"""Optional Meshtastic bridge: connects Beacon to a Meshtastic radio (LoRa mesh, no internet,
no cell towers) plugged in by USB or reachable on the Wi-Fi.

  - Text messages heard on the mesh appear on the Board.
  - "SAFE <name>" or "HELP <name> <details>" sent from any radio becomes a check-in on the roster,
    and the sender gets a short confirmation.
  - Board posts can be sent out over the mesh (guests only if the Beacon computer allows it).
  - Nodes that share their position show up on the Map, and a radio with GPS gives the Mac its location.
  - Plug and play: a radio plugged in by USB connects by itself (unless you turned that off or
    disconnected it by hand; replugging it reconnects).

The Meshtastic Python library (GPL-3.0) is an add-on: the drive builder installs it, and Beacon
works the same without it.
"""
import importlib.util
import threading
import time

MAX_TEXT = 200  # Meshtastic text payloads are about 230 bytes; leave room for the sender's name


def installed() -> bool:
    return importlib.util.find_spec("meshtastic") is not None


def serial_ports() -> list[str]:
    """USB serial devices, which is how a Meshtastic radio shows up. Built-in ports (Bluetooth, a Mac's
    debug console, a PC's COM1) have no USB vendor ID and are left out, so plug and play never grabs them."""
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return sorted(p.device for p in list_ports.comports()
                  if getattr(p, "vid", None) is not None and not p.device.startswith("/dev/tty.") and "Bluetooth" not in p.device)


def _friendly(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    if "No such file" in msg or "could not open port" in msg or "No Serial Meshtastic device" in msg:
        return "No Meshtastic radio found. Plug it in with a data USB cable (some cables only charge) and try again."
    if "Permission denied" in msg:
        return "The Mac didn't allow access to the radio. Unplug it, plug it back in, and try again."
    if "timed out" in msg.lower() or "Timed out" in msg:
        return "The radio didn't answer. Restart it and try again."
    return msg[:200]


class MeshBridge:
    def __init__(self, board, audit=None, factory=None):
        self.board, self.audit, self.factory = board, audit, factory
        self.iface = None
        self.state, self.error, self.target = "off", "", ""
        self.allow_guests = False
        self.auto = True            # connect a radio as soon as it's plugged in
        self.paused = False         # set by a manual disconnect, cleared when the radio is replugged
        self._ports_seen: list[str] = []
        self.lock = threading.Lock()
        self._subscribed = False

    # ------------------------------------------------------------ connection
    def connect(self, port: str | None = None, host: str | None = None):
        self.disconnect()
        self.state, self.error = "connecting", ""
        threading.Thread(target=self._open, args=(port, host), daemon=True).start()

    def _open(self, port, host):
        try:
            if self.factory:          # tests and simulations
                iface = self.factory(port, host)
            else:
                from pubsub import pub
                if host:
                    from meshtastic.tcp_interface import TCPInterface
                    iface = TCPInterface(hostname=host)
                else:
                    from meshtastic.serial_interface import SerialInterface
                    iface = SerialInterface(devPath=port or None)
                if not self._subscribed:
                    pub.subscribe(self.on_receive, "meshtastic.receive.text")
                    pub.subscribe(self.on_lost, "meshtastic.connection.lost")
                    self._subscribed = True
            with self.lock:
                self.iface = iface
                self.state, self.target = "connected", host or port or "USB"
            if self.audit:
                self.audit.add("mesh-connected", "127.0.0.1", "", f"Connected to the Meshtastic radio {self.me() or ''} ({self.target})".replace(" ()", ""))
        except Exception as e:  # missing library, no radio, unplugged mid-way...
            with self.lock:
                self.iface, self.state, self.error = None, "error", _friendly(e)

    def watch_once(self, ports: list[str] | None = None) -> bool:
        """Plug and play: connect when a radio appears. Returns True if it started connecting."""
        ports = serial_ports() if ports is None else ports
        before, self._ports_seen = self._ports_seen, ports
        changed = ports != before
        if changed:
            self.paused = False
        if not self.auto or self.paused or not ports or self.state in ("connected", "connecting"):
            return False
        if self.state == "error" and not changed:  # don't keep retrying a radio that failed; wait for a replug
            return False
        fresh = [p for p in ports if p not in before]  # the one just plugged in, if there is one
        self.connect(port=(fresh or ports)[0])
        return True

    def watch(self, every: float = 8.0):
        while True:
            try:
                self.watch_once()
            except Exception:
                pass
            time.sleep(every)

    def disconnect(self, manual: bool = False):
        if manual:
            self.paused = True
        with self.lock:
            iface, self.iface = self.iface, None
            self.state, self.target = "off", ""
        if iface:
            try:
                iface.close()
            except Exception:
                pass

    def on_lost(self, interface=None):
        with self.lock:
            self.iface, self.state, self.error = None, "error", "The radio was disconnected. Plug it back in and connect again."

    # ------------------------------------------------------------ messages
    def on_receive(self, packet, interface=None):
        decoded = (packet or {}).get("decoded") or {}
        text = (decoded.get("text") or "").strip()
        if not text:
            return
        node = packet.get("fromId") or str(packet.get("from", ""))
        channel = int(packet.get("channel") or 0)
        sender = self.name_of(node)
        checkin = self.board.parse_checkin(text)
        if checkin:  # "SAFE Garcia family" or "HELP Unit 4B: out of insulin"
            status, rest = checkin
            name, details = rest.split(":", 1) if ":" in rest else (rest, "")
            name = name.strip()[:40] or sender
            self.board.add("checkin", details.strip(), name=name, status=status, source="mesh",
                           channel=channel, mesh_id=node)
            self.send(f"Beacon: checked in {name} as {'NEEDS HELP' if status == 'help' else 'safe'}.", channel, node)
            return
        self.board.add("mesh", text, name=sender, source="mesh", channel=channel, mesh_id=node)

    def send(self, text: str, channel: int = 0, to: str = "^all") -> bool:
        iface = self.iface
        if not iface:
            return False
        try:
            iface.sendText(text[:MAX_TEXT], destinationId=to, channelIndex=channel)
            return True
        except Exception as e:
            self.error = _friendly(e)
            return False

    # ------------------------------------------------------------ what the radio knows
    def name_of(self, node_id: str) -> str:
        n = ((getattr(self.iface, "nodes", None) or {}).get(node_id) or {}).get("user") or {}
        return n.get("longName") or n.get("shortName") or node_id or "Unknown radio"

    def position(self) -> dict | None:
        """The connected radio's own GPS fix, if it has one."""
        try:
            pos = (self.iface.getMyNodeInfo() or {}).get("position") or {}
            lat, lon = pos.get("latitude"), pos.get("longitude")
            if lat is not None and lon is not None and (abs(lat) > 0.0001 or abs(lon) > 0.0001):
                return {"lat": round(float(lat), 5), "lon": round(float(lon), 5), "time": pos.get("time")}
        except Exception:
            pass
        return None

    def me(self) -> str:
        try:
            u = (self.iface.getMyNodeInfo() or {}).get("user") or {}
            return u.get("longName") or u.get("shortName") or ""
        except Exception:
            return ""

    def nodes(self) -> list[dict]:
        out = []
        for key, n in list((getattr(self.iface, "nodes", None) or {}).items()):
            user, pos = n.get("user") or {}, n.get("position") or {}
            out.append({"id": user.get("id") or key, "name": user.get("longName") or key,
                        "short": user.get("shortName") or "", "last_heard": n.get("lastHeard"),
                        "snr": n.get("snr"), "hops": n.get("hopsAway"),
                        "battery": (n.get("deviceMetrics") or {}).get("batteryLevel"),
                        "lat": pos.get("latitude"), "lon": pos.get("longitude")})
        return sorted(out, key=lambda x: -(x["last_heard"] or 0))

    def status(self) -> dict:
        return {"installed": installed() or self.factory is not None, "state": self.state, "error": self.error,
                "target": self.target, "me": self.me() if self.iface else "", "allow_guests": self.allow_guests,
                "auto": self.auto, "position": self.position() if self.iface else None,
                "nodes": len(getattr(self.iface, "nodes", None) or {}) if self.iface else 0}
