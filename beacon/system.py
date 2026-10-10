"""Startup resource check: what is this machine, and what brain should it run?"""
import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path

from . import models

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _gpu() -> str:
    sysname = platform.system()
    try:
        if sysname == "Darwin":
            if platform.machine() == "arm64":
                return "Apple Silicon GPU (Metal) — fast"
            return "Intel Mac — CPU only, slower"
        if shutil.which("nvidia-smi"):
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                text=True, timeout=5).strip().splitlines()
            if out:
                return f"NVIDIA {out[0]} — fast"
    except Exception:
        pass
    return "No supported GPU found — CPU only"


def _battery() -> dict | None:
    if not psutil:
        return None
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return {"percent": round(b.percent), "plugged_in": bool(b.power_plugged)}
    except Exception:
        return None


def drive_info(path: str) -> dict:
    """Which drive Beacon runs from, and whether it's encrypted (macOS; unknown elsewhere)."""
    p = Path(path).resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    info = {"mount": str(p), "encrypted": None, "format": "", "internal": None}
    if platform.system() != "Darwin" or not shutil.which("diskutil"):
        return info
    try:
        out = subprocess.run(["diskutil", "info", "-plist", str(p)], capture_output=True, timeout=10).stdout
        d = plistlib.loads(out)
        info["format"] = d.get("FilesystemName") or d.get("FilesystemType") or ""
        info["encrypted"] = bool(d.get("FileVault") or d.get("Encryption"))
        info["internal"] = bool(d.get("Internal"))
    except Exception:
        pass
    return info


def check(data_root: str, installed_models: list[str]) -> dict:
    ram = models.system_ram_gb()
    avail = None
    if psutil:
        avail = round(psutil.virtual_memory().available / 1024 ** 3, 1)
    disk = shutil.disk_usage(Path(data_root))
    rec = models.recommended(ram)
    active = models.best_model(installed_models, ram)
    prof = models.profile(ram)
    battery = _battery()

    notes = []
    if not active:
        notes.append(f"No AI model is on this drive yet. Download {rec['model']} in the Library tab.")
    elif active != rec["model"]:
        notes.append(f"This computer could run a stronger brain ({rec['model']}). "
                     f"Using {active} until you download it in the Library tab.")
    if avail is not None and avail < 3:
        notes.append(f"Only {avail} GB of memory is free. Close other apps for faster answers.")
    if battery and not battery["plugged_in"] and battery["percent"] < 30:
        notes.append(f"Battery at {battery['percent']}%. The AI uses a lot of power; plug in "
                     "if you can, or use the quick cards to save battery.")
    if disk.free < 5 * 1024 ** 3:
        notes.append("Less than 5 GB free on the drive. You won't be able to add much more.")
    if "CPU only" in _gpu():
        notes.append("No GPU acceleration: expect slower answers. The light model keeps it usable.")
    drive = drive_info(data_root)
    if drive["encrypted"] is False and not drive["internal"]:
        notes.append("This drive isn't encrypted, so anyone who finds it can read your household info. "
                     "START-HERE.txt shows how to lock it with a password.")

    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "chip": models.chip(),
        "cpu_cores": os.cpu_count(),
        "gpu": _gpu(),
        "ram_gb": round(ram, 1),
        "ram_free_gb": avail,
        "disk_free_gb": round(disk.free / 1024 ** 3, 1),
        "disk_total_gb": round(disk.total / 1024 ** 3, 1),
        "battery": battery,
        "recommended": rec,
        "active_model": active,
        "profile": prof,
        "tiers": [{**t, "fits": ram >= t["min_ram_gb"],
                   "installed": any(models._same(t["model"], m) for m in installed_models)}
                  for t in models.TIERS],
        "notes": notes,
        "drive": drive,
    }
