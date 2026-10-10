"""Pick the strongest downloaded model that this Mac's memory can actually run."""
import platform
import subprocess

# Strongest first. min_ram_gb = total system RAM needed to run it comfortably
# alongside the app and macOS. Edit freely; build_usb.sh reads the same list.
TIERS = [
    {"model": "qwen3.6:27b", "min_ram_gb": 32, "size_gb": 17, "label": "Max (32 GB+ Macs)"},
    {"model": "qwen3:14b",   "min_ram_gb": 16, "size_gb": 9.3, "label": "Strong (16 GB Macs)"},
    {"model": "qwen3:8b",    "min_ram_gb": 12, "size_gb": 5.2, "label": "Balanced"},
    {"model": "qwen3:4b",    "min_ram_gb": 0,  "size_gb": 2.6, "label": "Light (8 GB / Intel Macs)"},
]


def system_ram_gb() -> float:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return int(out.strip()) / 1024 ** 3
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 1024 ** 2
    except Exception:
        return 8.0


def _same(a: str, b: str) -> bool:
    norm = lambda m: m if ":" in m else f"{m}:latest"
    return norm(a) == norm(b)


def best_model(installed: list[str], ram_gb: float | None = None) -> str | None:
    """Strongest tier model that's installed and fits RAM; else any installed chat model."""
    ram = system_ram_gb() if ram_gb is None else ram_gb
    for tier in TIERS:
        if ram >= tier["min_ram_gb"] and any(_same(tier["model"], m) for m in installed):
            return tier["model"]
    chat = [m for m in installed if "embed" not in m]
    return chat[0] if chat else None
