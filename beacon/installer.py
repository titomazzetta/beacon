"""Command-line installer (used by build_usb.sh; also handy on its own).

  python -m beacon.installer --list
  python -m beacon.installer --tier core
  python -m beacon.installer --tier extended --bands medical,water-food
  python -m beacon.installer --models "qwen3:4b qwen3:14b"
  python -m beacon.installer --maps places,world --region "Denver" --radius 300
"""
import argparse
import sys
import time

from . import config, library, mapdata, models
from .ollama_client import Ollama


def human(n: int) -> str:
    if not n:
        return "?"
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{max(1, n // 1024 ** 2)} MB"


def wait(downloader: library.Downloader, label: str):
    last = ""
    while True:
        jobs = downloader.status()
        active = [j for j in jobs if j["state"] in ("queued", "downloading")]
        cur = next((j for j in jobs if j["state"] == "downloading"), None)
        if cur:
            pct = f"{100 * cur['done'] / cur['total']:.0f}%" if cur.get("total") else ""
            line = f"  {label}: {cur['title'][:50]} {pct} {cur.get('detail', '')[:50]}"
            if line != last:
                print("\r" + line.ljust(110), end="", flush=True)
                last = line
        if not active:
            break
        time.sleep(1)
    print()
    for j in downloader.status():
        mark = {"done": "✓", "failed": "✗", "cancelled": "-"}.get(j["state"], "?")
        print(f"  {mark} {j['title']}" + (f"  ({j['error']})" if j.get("error") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install Beacon library content.")
    ap.add_argument("--list", action="store_true", help="show bands, tiers and items")
    ap.add_argument("--tier", choices=library.TIER_ORDER)
    ap.add_argument("--bands", help="comma-separated band ids (default: all)")
    ap.add_argument("--models", help='models to download, e.g. "qwen3:4b qwen3:14b" or "auto"')
    ap.add_argument("--maps", default="", help="comma list: places,world")
    ap.add_argument("--region", help="build a detailed map around this place name")
    ap.add_argument("--radius", type=float, default=300, help="region radius in km")
    a = ap.parse_args(argv)

    cfg = config.load()
    catalog = library.load_catalog()
    if a.list:
        for band in catalog["bands"]:
            print(f"\n{band['title']}  [{band['id']}]")
            for it in band["items"]:
                print(f"  {it['tier']:<10} {it['type']:<5} {it['title']}")
        return

    data_root = cfg["data_root"]
    from pathlib import Path
    installed = library.Installed(str(Path(cfg["index_path"]).parent / "installed.json"), data_root)
    kcat = library.KiwixCatalog(str(Path(cfg["index_path"]).parent / "kiwix_catalog.json"))
    integrity = library.Integrity(str(Path(cfg["index_path"]).parent / "integrity.json"), data_root)
    dl = library.Downloader(installed, integrity=integrity)

    if a.models:
        ollama = Ollama(cfg["ollama_url"])
        if not ollama.is_up():
            sys.exit("Ollama isn't running at " + cfg["ollama_url"])
        names = [models.EMBED_MODEL] + (
            [models.recommended()["model"]] if a.models == "auto" else a.models.split())
        for name in names:
            print(f"\n▸ AI model {name}")
            last = ""
            for msg in ollama.pull(name):
                pct = f" {100 * msg['completed'] / msg['total']:.0f}%" if msg.get("total") and msg.get("completed") else ""
                line = f"  {msg.get('status', '')}{pct}"
                if line != last:
                    print("\r" + line.ljust(80), end="", flush=True)
                    last = line
            print()

    if a.tier:
        bands = a.bands.split(",") if a.bands else None
        items = library.items_for_tier(catalog, a.tier, bands)
        todo, total = [], 0
        print(f"\n▸ Library tier '{a.tier}': looking up {len(items)} items…")
        for it in items:
            if installed.file_for(it["id"]) or (it["type"] in ("pdf", "text", "page") and not it.get("files")
                                                and library.destination(it, cfg).exists()):
                continue
            try:
                if it["type"] == "zim":
                    r = kcat.resolve(it)
                    if not r:
                        print(f"  ! not found in Kiwix catalog: {it['title']}")
                        continue
                    total += r["size"]
                todo.append(it)
            except Exception as e:
                print(f"  ! {it['title']}: {e}")
        free = library.free_bytes(data_root)
        print(f"  {len(todo)} to download, about {human(total)} (plus small PDFs). Free: {human(free)}")
        if total > free:
            print("  ! Not enough space for everything; downloads will stop when the drive is full.")
        for it in todo:
            library.queue_item(it, dl, kcat, cfg)
        wait(dl, "Library")

    maps = [m for m in a.maps.split(",") if m]
    if "places" in maps:
        dl.add_task("map-places", "World place names", lambda j: mapdata.build_places(data_root, j), "places")
    if "world" in maps:
        dl.add_task("map-world", "World map", lambda j: mapdata.build_world(data_root, j), "map")
    if a.region:
        from .places import Places
        p = Places(str(mapdata.maps_dir(data_root) / "places.tsv"))
        if not p.available:  # need names first
            dl.add_task("map-places", "World place names", lambda j: mapdata.build_places(data_root, j), "places")
            wait(dl, "Maps")
            p = Places(str(mapdata.maps_dir(data_root) / "places.tsv"))
        hits = p.search(a.region, 1)
        if hits:
            h = hits[0]
            print(f"\n▸ Region map around {h['label']} ({a.radius:.0f} km)")
            dl.add_task("map-region", f"Detailed map: {h['label']}",
                        lambda j: mapdata.build_region(data_root, j, h["label"].split(",")[0], h["lat"], h["lon"], a.radius), "map")
        else:
            print(f"  ! couldn't find '{a.region}'")
    if maps or a.region:
        wait(dl, "Maps")


if __name__ == "__main__":
    main()
