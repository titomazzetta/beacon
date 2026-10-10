"""Optional Meshtastic bridge: connects Beacon to a Meshtastic radio (LoRa mesh, no internet,
no cell towers) plugged in by USB or reachable on the Wi-Fi.

  - Text messages heard on the mesh appear on the Board.
  - "SAFE <name>" or "HELP <name> <details>" sent from any radio becomes a check-in on the roster,
    and the sender gets a short confirmation.
  - Board posts can be sent out over the mesh (guests only if the Beacon computer allows it).
  - Nodes that share their position show up on the Map.

The Meshtastic Python library (GPL-3.0) is an add-on: the drive builder installs it, and Beacon
works the same without it.
"""
import importlib.util
import threading

MAX_TEXT = 200  # Meshtastic text payloads are about 230 bytes; leave room for the sender's name


def installed() -> bool:
    return importlib.util.find_spec("meshtastic") is not None


def serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    ports = [p.device for p in list_ports.comports()]
    return [p for p in ports if not p.startswith("/dev/tty.") and "Bluetooth" not in p]


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

    def disconnect(self):
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
                "nodes": len(getattr(self.iface, "nodes", None) or {}) if self.iface else 0}
