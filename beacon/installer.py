"""Command-line installer (used by build_usb.sh; also handy on its own).

  python -m beacon.installer --list
  python -m beacon.installer --tier core
  python -m beacon.installer --tier extended --bands medical,water-food
  python -m beacon.installer --models "qwen3:4b qwen3:14b"
  python -m beacon.installer --maps places,world --region "Denver" --radius 300
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import config, library, mapdata, models
from .ollama_client import Ollama


def human(n: int) -> str:
    if not n:
        return "?"
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{max(1, n // 1024 ** 2)} MB"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _note_failure(path: Path, item_id: str, title: str, error: str):
    d = _load(path)
    d[item_id] = {"title": title, "error": error[:200], "at": int(time.time())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=1))


def _forget_failure(path: Path, item_id: str):
    d = _load(path)
    if d.pop(item_id, None) is not None:
        path.write_text(json.dumps(d, indent=1))


def report(catalog: dict, installed: library.Installed, cfg: dict, failures_path: Path,
           tier: str = "everything", optional: bool = False) -> str:
    """Every item the drive should have, with its state: the proof that the library is complete."""
    failed = _load(failures_path)
    lines, ok, bad = [], 0, []
    for it in library.items_for_tier(catalog, tier, None, optional):
        have = installed.file_for(it["id"])
        if not have and it["type"] in ("pdf", "text", "page") and not it.get("files"):
            d = library.destination(it, cfg)
            have = str(d) if d.exists() else None
        problem = library.file_problem(have) if have and Path(have).is_file() else None
        if have and not problem:
            ok += 1
            size = sum(f.stat().st_size for f in Path(have).rglob("*") if f.is_file()) if Path(have).is_dir() else Path(have).stat().st_size
            lines.append(f"  ✓ {it['title'][:60]:60} {human(size):>8}")
        else:
            why = problem or failed.get(it["id"], {}).get("error") or "not downloaded"
            bad.append(it["title"])
            lines.append(f"  ✗ {it['title'][:60]:60}   {why[:90]}")
    head = f"Library report ({tier} tier{', with optional items' if optional else ''}): {ok} of {ok + len(bad)} items on the drive"
    tail = "" if not bad else f"\nMissing or broken ({len(bad)}): run the builder again, or retry them in the Library tab.\n"
    return "\n" + head + "\n" + "\n".join(lines) + tail


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
    ap.add_argument("--optional", action="store_true", help="include optional items too (Wikipedia with images)")
    ap.add_argument("--report", action="store_true", help="what's on the drive, what failed and why")
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

    failures_path = Path(cfg["index_path"]).parent / "failed.json"
    dl.on_done = lambda job, _p=failures_path: _forget_failure(_p, job["id"])

    if a.tier and not a.report:  # --report only looks
        bands = a.bands.split(",") if a.bands else None
        items = library.items_for_tier(catalog, a.tier, bands, a.optional)
        todo, total = [], 0
        print(f"\n▸ Library tier '{a.tier}': looking up {len(items)} items…")
        for it in items:
            have = installed.file_for(it["id"])
            if not have and it["type"] in ("pdf", "text", "page") and not it.get("files"):
                d = library.destination(it, cfg)
                have = str(d) if d.exists() else None
            if have and Path(have).is_file() and library.file_problem(have):
                print(f"  ! {it['title']}: {library.file_problem(have)} Trying again.")
                Path(have).unlink()
                installed.forget(it["id"])
                have = None
            if have:
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
                _note_failure(failures_path, it["id"], it["title"], str(e))
        free = library.free_bytes(data_root)
        print(f"  {len(todo)} to download, about {human(total)} (plus small PDFs). Free: {human(free)}")
        if total > free:
            print("  ! Not enough space for everything; downloads will stop when the drive is full.")
        for it in todo:
            library.queue_item(it, dl, kcat, cfg)
        wait(dl, "Library")
        for j in dl.status():
            if j["state"] == "failed":
                _note_failure(failures_path, j["id"], j["title"], j.get("error", ""))

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

    if a.report:
        print(report(catalog, installed, cfg, failures_path, a.tier or "everything", a.optional))


if __name__ == "__main__":
    main()
