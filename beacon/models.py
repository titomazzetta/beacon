"""The 'brain': pick the strongest model this machine can run and size everything to it."""
import os
import platform
import subprocess

# Strongest first. min_ram_gb = total system memory needed to run it comfortably next to
# macOS and the app. build_usb.sh and the Library tab read this list.
TIERS = [
    {"model": "gpt-oss:120b", "min_ram_gb": 96, "size_gb": 65,  "label": "Titan (96 GB+ workstations)"},
    {"model": "qwen3.6:27b",  "min_ram_gb": 32, "size_gb": 17,  "label": "Max (32 GB+ Macs)"},
    {"model": "gpt-oss:20b",  "min_ram_gb": 24, "size_gb": 14,  "label": "Heavy (24 GB Macs)"},
    {"model": "qwen3:14b",    "min_ram_gb": 16, "size_gb": 9.3, "label": "Strong (16 GB Macs)"},
    {"model": "qwen3:8b",     "min_ram_gb": 12, "size_gb": 5.2, "label": "Balanced (12 GB)"},
    {"model": "qwen3:4b",     "min_ram_gb": 0,  "size_gb": 2.6, "label": "Light (8 GB & Intel Macs)"},
]
EMBED_MODEL = "nomic-embed-text"

# How much the brain reads per question. More memory = longer context = more sources.
PROFILES = [
    {"min_ram_gb": 48, "name": "Max",      "num_ctx": 32768, "sources": 12, "chars": 4000},
    {"min_ram_gb": 24, "name": "Strong",   "num_ctx": 16384, "sources": 9,  "chars": 3000},
    {"min_ram_gb": 14, "name": "Standard", "num_ctx": 8192,  "sources": 6,  "chars": 2500},
    {"min_ram_gb": 0,  "name": "Light",    "num_ctx": 4096,  "sources": 4,  "chars": 1500},
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


def chip() -> str:
    try:
        if platform.system() == "Darwin":
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                           text=True).strip()
    except Exception:
        pass
    return f"{platform.machine()}, {os.cpu_count()} cores"


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


def recommended(ram_gb: float | None = None) -> dict:
    """Strongest tier this machine can run (whether or not it's downloaded yet)."""
    ram = system_ram_gb() if ram_gb is None else ram_gb
    return next(t for t in TIERS if ram >= t["min_ram_gb"])


def profile(ram_gb: float | None = None) -> dict:
    ram = system_ram_gb() if ram_gb is None else ram_gb
    return next(p for p in PROFILES if ram >= p["min_ram_gb"])
