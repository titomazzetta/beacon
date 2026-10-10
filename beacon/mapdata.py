"""Builds the offline map data: world place names, a world basemap and a detailed region.

Runs on a computer with internet (from the Library tab or the installer). Uses:
- GeoNames (CC BY 4.0) for place names
- Protomaps daily OpenStreetMap build (ODbL) + the pmtiles CLI to cut out what's needed
"""
import datetime as dt
import io
import os
import platform
import re
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

import requests

UA = {"User-Agent": "Beacon-offline-library/0.2"}
GEONAMES = "https://download.geonames.org/export/dump/"


def maps_dir(data_root: str) -> Path:
    d = Path(data_root) / "maps"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ places

def convert_geonames(cities_txt: str, country_info: str, admin1: str) -> list[str]:
    """GeoNames dumps → places.tsv lines (name, ascii, lat, lon, cc, admin1, country, pop)."""
    countries = {}
    for line in country_info.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        c = line.split("\t")
        if len(c) > 4:
            countries[c[0]] = c[4]
    admins = {}
    for line in admin1.splitlines():
        c = line.split("\t")
        if len(c) > 1:
            admins[c[0]] = c[1]
    out = []
    for line in cities_txt.splitlines():
        c = line.split("\t")
        if len(c) < 15:
            continue
        name, ascii_, lat, lon, cc, a1, pop = c[1], c[2], c[4], c[5], c[8], c[10], c[14]
        out.append("\t".join([name, ascii_, lat, lon, cc, admins.get(f"{cc}.{a1}", ""),
                              countries.get(cc, cc), pop or "0"]))
    return out


def build_places(data_root: str, job: dict, http=requests) -> Path:
    job["detail"] = "Downloading world place names (GeoNames)…"
    z = http.get(GEONAMES + "cities5000.zip", headers=UA, timeout=120)
    z.raise_for_status()
    cities = zipfile.ZipFile(io.BytesIO(z.content)).read("cities5000.txt").decode("utf-8")
    info = http.get(GEONAMES + "countryInfo.txt", headers=UA, timeout=60).text
    adm = http.get(GEONAMES + "admin1CodesASCII.txt", headers=UA, timeout=60).text
    lines = convert_geonames(cities, info, adm)
    dest = maps_dir(data_root) / "places.tsv"
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    job["detail"] = f"{len(lines):,} places worldwide"
    return dest


# ------------------------------------------------------------------ pmtiles CLI + builds

def _asset_pattern() -> str:
    sysname, mach = platform.system(), platform.machine().lower()
    arch = "arm64" if mach in ("arm64", "aarch64") else "x86_64"
    return {"Darwin": f"Darwin_{arch}", "Windows": "Windows_x86_64",
            "Linux": f"Linux_{arch}"}.get(sysname, f"Linux_{arch}")


def github_assets(repo: str, http=requests) -> list[tuple[str, str]]:
    """(name, url) for a repo's latest release. Uses the public release page first (no API
    rate limit), then the API."""
    try:
        r = http.get(f"https://github.com/{repo}/releases/latest", headers=UA, timeout=30,
                     allow_redirects=False)
        tag = r.headers.get("Location", "").rsplit("/tag/", 1)[-1]
        if tag:
            page = http.get(f"https://github.com/{repo}/releases/expanded_assets/{tag}",
                            headers=UA, timeout=30).text
            names = sorted(set(re.findall(rf'/{re.escape(repo)}/releases/download/{re.escape(tag)}/([^"?#]+)', page)))
            if names:
                return [(n, f"https://github.com/{repo}/releases/download/{tag}/{n}") for n in names]
    except requests.RequestException:
        pass
    rel = http.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=UA, timeout=30).json()
    return [(a["name"], a["browser_download_url"]) for a in rel.get("assets", [])]


def pmtiles_cli(data_root: str, http=requests) -> Path:
    tools = Path(data_root) / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    exe = tools / ("pmtiles.exe" if platform.system() == "Windows" else "pmtiles")
    if exe.exists():
        return exe
    pat = _asset_pattern()
    name, url = next((n, u) for n, u in github_assets("protomaps/go-pmtiles", http) if pat in n)
    blob = http.get(url, headers=UA, timeout=300).content
    asset = {"name": name}
    if asset["name"].endswith(".zip"):
        zf = zipfile.ZipFile(io.BytesIO(blob))
        member = next(n for n in zf.namelist() if n.split("/")[-1] in ("pmtiles", "pmtiles.exe"))
        exe.write_bytes(zf.read(member))
    else:
        tf = tarfile.open(fileobj=io.BytesIO(blob))
        member = next(m for m in tf.getmembers() if m.name.split("/")[-1] == "pmtiles")
        exe.write_bytes(tf.extractfile(member).read())
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def latest_build(http=requests) -> str:
    """Protomaps keeps a week of daily planet builds at build.protomaps.com/YYYYMMDD.pmtiles."""
    today = dt.date.today()
    for back in range(0, 12):
        url = f"https://build.protomaps.com/{(today - dt.timedelta(days=back)):%Y%m%d}.pmtiles"
        try:
            if http.head(url, headers=UA, timeout=15).status_code == 200:
                return url
        except requests.RequestException:
            continue
    raise RuntimeError("Couldn't find a recent Protomaps build")


def _extract(cli: Path, src: str, dest: Path, maxzoom: int, bbox: str | None, job: dict):
    cmd = [str(cli), "extract", src, str(dest), f"--maxzoom={maxzoom}"]
    if bbox:
        cmd.append(f"--bbox={bbox}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:  # pmtiles prints progress lines
        line = line.strip()
        if line:
            job["detail"] = line[-120:]
        if job.get("state") == "cancelled":
            proc.terminate()
            return
    if proc.wait() != 0:
        raise RuntimeError(f"pmtiles extract failed: {job.get('detail', '')}")


def build_world(data_root: str, job: dict, maxzoom: int = 6, http=requests) -> Path:
    cli = pmtiles_cli(data_root, http)
    src = latest_build(http)
    dest = maps_dir(data_root) / "world.pmtiles"
    job["detail"] = f"Cutting world map (zoom 0–{maxzoom}) from {src.rsplit('/', 1)[-1]}…"
    _extract(cli, src, dest, maxzoom, None, job)
    return dest


def bbox_around(lat: float, lon: float, radius_km: float) -> str:
    import math
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.05))
    return (f"{max(lon - dlon, -180):.4f},{max(lat - dlat, -85):.4f},"
            f"{min(lon + dlon, 180):.4f},{min(lat + dlat, 85):.4f}")


def safe_name(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "region"


def build_region(data_root: str, job: dict, label: str, lat: float, lon: float,
                 radius_km: float = 300, maxzoom: int = 13, http=requests) -> Path:
    cli = pmtiles_cli(data_root, http)
    src = latest_build(http)
    dest = maps_dir(data_root) / f"region-{safe_name(label)}.pmtiles"
    job["detail"] = f"Cutting detailed map of {label} ({radius_km:.0f} km, zoom {maxzoom})…"
    _extract(cli, src, dest, maxzoom, bbox_around(lat, lon, radius_km), job)
    return dest


def installed_maps(data_root: str) -> list[dict]:
    d = maps_dir(data_root)
    out = []
    for p in sorted(d.glob("*.pmtiles")):
        out.append({"file": p.name, "size_mb": round(p.stat().st_size / 1024 ** 2),
                    "kind": "world" if p.name == "world.pmtiles" else "region"})
    return out
