"""Beacon web app: a local GUI at http://127.0.0.1:8642. Works with no internet."""
import html
import json
import re
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from . import checks, config, library, mapdata, models, plans, rag, system
from .kiwix_source import KiwixLibrary
from .manuals import ManualIndex
from .ollama_client import Ollama, OllamaError
from .places import Places, route_summary

STATIC = Path(__file__).resolve().parent.parent / "static"


READER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title><style>
:root{--bg:#f6f1e7;--text:#2a241b;--muted:#7a6f5d}
@media (prefers-color-scheme:dark){:root{--bg:#14120f;--text:#e9e1d2;--muted:#9a8f7c}}
body{margin:0;background:var(--bg);color:var(--text);font:19px/1.7 Georgia,"Iowan Old Style",serif}
main{max-width:680px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:28px;margin:0 0 6px} .bar{position:sticky;top:0;background:var(--bg);padding:10px 22px;font:14px -apple-system,sans-serif;color:var(--muted);display:flex;gap:14px;justify-content:center}
.bar button{font:inherit;background:none;border:1px solid var(--muted);color:var(--text);border-radius:6px;padding:3px 10px;cursor:pointer}
p{margin:0 0 1em;white-space:pre-line}
</style></head><body>
<div class="bar"><button onclick="document.body.style.fontSize=(parseFloat(getComputedStyle(document.body).fontSize)+2)+'px'">A+</button>
<button onclick="document.body.style.fontSize=(parseFloat(getComputedStyle(document.body).fontSize)-2)+'px'">A−</button>
<button onclick="try{localStorage.setItem(location.pathname,scrollY)}catch(e){}">Bookmark</button>
<button onclick="try{scrollTo(0,+localStorage.getItem(location.pathname)||0)}catch(e){}">Go to bookmark</button></div>
<main><h1>{{title}}</h1>{{body}}</main></body></html>"""


PROFILE_FIELDS = {
    "home": "Home address / area", "people": "People in the household (ages, needs)",
    "medical": "Medical conditions, medications & allergies", "contacts": "Emergency contacts & phone numbers",
    "meeting": "Meeting places (near home, neighborhood, out of town)", "outside_contact": "Out-of-area contact",
    "vehicles": "Vehicles, fuel & range", "skills": "Skills & key gear", "documents": "Where documents are kept",
    "notes": "Other notes",
}

BINDER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Beacon binder</title><style>
body{font:12.5pt/1.45 Georgia,serif;color:#111;max-width:760px;margin:0 auto;padding:24px}
h1{font:700 20pt -apple-system,Segoe UI,Arial,sans-serif;border-bottom:3px solid #111;padding-bottom:4px;margin:0 0 10px}
h2{font:700 13pt -apple-system,Segoe UI,Arial,sans-serif;margin:16px 0 4px}
section{page-break-after:always} pre{font:9.5pt/1.35 Menlo,Consolas,monospace;white-space:pre-wrap}
table{border-collapse:collapse;width:100%;margin:6px 0} td,th{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}
table.info th{width:34%;background:#f2f2f2} .cover{text-align:center;padding-top:30vh} .cover h1{border:0;font-size:40pt}
.noprint{position:fixed;top:12px;right:12px} @media print{.noprint{display:none}}
</style></head><body><button class="noprint" onclick="print()">Print / Save as PDF</button>
<section class="cover"><h1>BEACON</h1><p>Emergency binder · printed {{date}}</p><p>Keep with your emergency supplies.</p></section>
{{body}}</body></html>"""


def mini_md(src: str) -> str:
    """Just enough Markdown for the printable binder (headings, lists, tables, bold)."""
    out, para, lst, table = [], [], None, []
    inline = lambda t: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(t))

    def flush():
        nonlocal para, lst, table
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>"); para = []
        if lst:
            tag = lst[0]; out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in lst[1:]) + f"</{tag}>"); lst = None
        if table:
            rows = [r for r in table if not re.match(r"^\|[\s:|-]+\|$", r)]
            out.append("<table>" + "".join("<tr>" + "".join(f"<td>{inline(c.strip())}</td>" for c in r.strip().strip("|").split("|")) + "</tr>" for r in rows) + "</table>"); table = []
    for line in src.splitlines():
        t = line.strip()
        if not t:
            flush(); continue
        m = re.match(r"^(#{1,3}) (.*)", t)
        if m:
            flush(); out.append(f"<h{min(len(m.group(1)), 2)}>{inline(m.group(2))}</h{min(len(m.group(1)), 2)}>"); continue
        if t.startswith("|"):
            if para or lst: flush()
            table.append(t); continue
        m = re.match(r"^(?:[-*•]|\d+[.)]) (.*)", t)
        if m:
            kind = "ol" if t[0].isdigit() else "ul"
            if para or table: flush()
            if lst is None or lst[0] != kind:
                flush(); lst = [kind]
            lst.append(m.group(1)); continue
        if lst or table: flush()
        para.append(t)
    flush()
    return "".join(out)


def sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


def create_app(cfg: dict | None = None, ollama=None, kiwix=None, manuals=None, http=None) -> Flask:
    cfg = cfg or config.load()
    data_root = cfg.get("data_root") or str(Path(cfg["zim_dir"]).parent.parent)
    app = Flask(__name__, static_folder=None)
    o = ollama or Ollama(cfg["ollama_url"])
    st = {
        "cfg": cfg, "ollama": o,
        "kiwix": kiwix if kiwix is not None else KiwixLibrary(cfg["zim_dir"]),
        "manuals": manuals if manuals is not None else ManualIndex(cfg["index_path"], o, cfg["embed_model"], cfg["manuals_dir"]),
        "places": Places(str(mapdata.maps_dir(data_root) / "places.tsv")),
        "ingest": {"running": False, "log": []},
        "check": {"running": False, "report": None},
        "online": {"at": 0, "value": False},
    }
    http_mod = http or library.requests
    catalog = library.load_catalog()
    kcat = library.KiwixCatalog(str(Path(cfg["index_path"]).parent / "kiwix_catalog.json"), http_mod)
    installed = library.Installed(str(Path(cfg["index_path"]).parent / "installed.json"), data_root)
    ingest_lock = threading.Lock()
    books_dir = str(Path(cfg.get("books_dir") or Path(cfg["manuals_dir"]).parent / "books"))

    # ------------------------------------------------------------ helpers
    def installed_models():
        return st["ollama"].models() if st["ollama"].is_up() else []

    def current_model(inst=None) -> str | None:
        inst = installed_models() if inst is None else inst
        wanted = st["cfg"].get("chat_model")
        if wanted and any(models._same(wanted, m) for m in inst):
            return wanted
        return models.best_model(inst)

    def start_ingest():
        if not ingest_lock.acquire(blocking=False):
            return False

        def run():
            log = st["ingest"]
            log.update(running=True, log=[])
            try:
                res = st["manuals"].ingest_dir(st["cfg"]["manuals_dir"],
                                               progress=lambda m: log["log"].append(m))
                log["log"].append(f"Done: {res['indexed']} new/changed, {res['unchanged']} unchanged, "
                                  f"{res['total_chunks']:,} passages searchable.")
            except Exception as e:
                log["log"].append(f"Error: {e}")
            finally:
                log["running"] = False
                ingest_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def on_download_done(job):
        if job["type"] == "zim":
            st["kiwix"].reload(st["cfg"]["zim_dir"])
        elif job["type"] in ("pdf", "text") and not str(job.get("dest", "")).startswith(books_dir):
            threading.Timer(1.0, start_ingest).start()
        elif job["type"] == "places":
            st["places"] = Places(str(mapdata.maps_dir(data_root) / "places.tsv"))

    downloader = library.Downloader(installed, on_done=on_download_done, http=http_mod)

    def online() -> bool:
        if time.time() - st["online"]["at"] > 60:
            st["online"] = {"at": time.time(), "value": library.is_online(http_mod)}
        return st["online"]["value"]

    # ------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        resp = send_from_directory(STATIC, name)
        if name.endswith(".mjs"):
            resp.headers["Content-Type"] = "text/javascript"
        return resp

    # ------------------------------------------------------------ system & brain
    @app.get("/api/system")
    def api_system():
        inst = installed_models()
        rep = system.check(data_root, inst)
        rep["engine_up"] = st["ollama"].is_up()
        rep["active_model"] = current_model(inst)
        rep["chosen"] = st["cfg"].get("chat_model") or ""
        return jsonify(rep)

    @app.get("/api/status")
    def status():
        return jsonify({
            "model": current_model(),
            "books": st["kiwix"].summary(),
            "manuals": st["manuals"].files(),
            "pending": st["manuals"].pending(st["cfg"]["manuals_dir"]),
            "ingest": st["ingest"],
            "jobs": downloader.status(),
        })

    @app.post("/api/model")
    def set_model():
        name = (request.json or {}).get("model", "")
        st["cfg"]["chat_model"] = name
        config.save({"chat_model": name})
        return jsonify({"model": name})

    # ------------------------------------------------------------ ask & plan
    def stream_answer(question, retrieval_query, history, use_library, extra_sources=()):
        prof = models.profile()
        yield sse("status", "Searching your library…")
        sources = list(extra_sources)
        if use_library:
            sources += rag.gather(retrieval_query, st["kiwix"], st["manuals"], prof)
        yield sse("sources", [{k: s.get(k, "") for k in ("kind", "book", "title", "ref")} for s in sources])
        model = current_model()
        if not model:
            yield sse("error", "No AI model is installed. Open the Library tab → Brain to download one.")
            return
        yield sse("status", f"Thinking with {model} ({prof['name']} brain)…")
        try:
            for piece in rag.answer(question, sources, history, st["ollama"], model, prof["num_ctx"]):
                yield sse("token", piece)
        except OllamaError as e:
            yield sse("error", str(e))
        yield sse("done", model)

    def sse_response(gen):
        return Response(gen, mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/ask")
    def ask():
        body = request.json or {}
        q = (body.get("question") or "").strip()
        if not q:
            abort(400, "empty question")
        return sse_response(stream_answer(q, q, body.get("history") or [], body.get("use_library", True)))

    @app.get("/api/plans")
    def plan_list():
        return jsonify(plans.public_list())

    @app.post("/api/plan")
    def make_plan():
        body = request.json or {}
        tpl = plans.get(body.get("template", ""))
        if not tpl:
            abort(404)
        answers = dict(body.get("answers") or {})
        prof = load_profile()  # My Info fills in what the form left blank
        for field, key in (("location", "home"), ("people", "people")):
            if not (answers.get(field) or "").strip() and prof.get(key):
                answers[field] = prof[key]
        extra = [f"{PROFILE_FIELDS[k]}: {prof[k]}" for k in
                 ("medical", "contacts", "meeting", "outside_contact", "vehicles", "skills") if prof.get(k)]
        if extra:
            answers["notes"] = (answers.get("notes", "") + "\nHousehold info: " + " | ".join(extra)).strip()
        place_ctx = ""
        loc = (answers.get("location") or "").strip()
        if loc and st["places"].available:
            hits = st["places"].search(loc, 1)
            if hits:
                h = hits[0]
                place_ctx = f"{h['label']} at {h['lat']:.3f}, {h['lon']:.3f}"
                dest = (answers.get("destination") or "").strip()
                dh = st["places"].search(dest, 1) if dest else []
                if dh:
                    r = route_summary(h, dh[0])
                    place_ctx += (f"; destination {dh[0]['label']} is {r['km']} km ({r['miles']} mi) "
                                  f"straight-line, bearing {r['bearing']}° {r['compass']}")
        query, instruction = plans.build(tpl, answers, place_ctx)
        return sse_response(stream_answer(instruction, query, [], True))

    # ------------------------------------------------------------ places & maps
    @app.get("/api/places")
    def places_search():
        return jsonify({"available": st["places"].available,
                        "results": st["places"].search(request.args.get("q", ""), 8)})

    @app.get("/api/places/nearest")
    def places_nearest():
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
        return jsonify(st["places"].nearest(lat, lon, 6))

    @app.post("/api/route")
    def route():
        b = request.json or {}
        return jsonify(route_summary(b["from"], b["to"]))

    @app.get("/api/maps")
    def maps_list():
        return jsonify({"maps": mapdata.installed_maps(data_root), "places": st["places"].available})

    @app.get("/maps/<path:name>")
    def map_file(name):
        p = (mapdata.maps_dir(data_root) / name).resolve()
        if p.parent != mapdata.maps_dir(data_root).resolve() or not p.exists():
            abort(404)
        return send_file(p, conditional=True)  # supports Range requests (needed by pmtiles)

    @app.post("/api/maps/build")
    def maps_build():
        b = request.json or {}
        kind = b.get("kind")
        if kind == "places":
            downloader.add_task("map-places", "World place names", lambda j: mapdata.build_places(data_root, j, http_mod), "places")
        elif kind == "world":
            downloader.add_task("map-world", "World map", lambda j: mapdata.build_world(data_root, j, int(b.get("maxzoom", 6)), http_mod), "map")
        elif kind == "region":
            label, lat, lon = b["label"], float(b["lat"]), float(b["lon"])
            radius, mz = float(b.get("radius", 300)), int(b.get("maxzoom", 13))
            downloader.add_task(f"map-region-{mapdata.safe_name(label)}", f"Detailed map: {label}",
                                lambda j: mapdata.build_region(data_root, j, label, lat, lon, radius, mz, http_mod), "map")
        else:
            abort(400)
        return jsonify({"queued": True})

    # ------------------------------------------------------------ library manager
    def item_status(it):
        f = installed.file_for(it["id"])
        if not f and it["type"] in ("pdf", "text"):
            p = library.destination(it, st["cfg"])
            f = str(p) if p.exists() else None
        job = downloader.jobs.get(it["id"])
        cached = kcat.cache.get(it["id"]) or {}
        return {
            "id": it["id"], "type": it["type"], "tier": it["tier"], "title": it["title"],
            "license": it.get("license", ""), "note": it.get("note", ""), "url": it.get("url", ""),
            "group": it.get("group"), "optional": it.get("optional", False), "shelf": it.get("shelf", False),
            "path": (str(Path(f).relative_to(books_dir)) if f and it.get("shelf") and f.startswith(books_dir) else ""),
            "installed": bool(f), "size": cached.get("size", 0),
            "job": {k: v for k, v in job.items() if k != "fn"} if job else None,
        }

    @app.get("/api/library")
    def lib():
        return jsonify({
            "tiers": catalog["tiers"],
            "bands": [{"id": b["id"], "title": b["title"], "items": [item_status({**i, "band": b["id"]}) for i in b["items"]]}
                      for b in catalog["bands"]],
            "buy_list": catalog.get("buy_list", {}),
            "free_gb": round(library.free_bytes(data_root) / 1024 ** 3, 1),
            "online": online(),
            "jobs": downloader.status(),
            "maps": mapdata.installed_maps(data_root),
            "places": st["places"].available,
        })

    @app.post("/api/library/sizes")
    def lib_sizes():
        """Look up live sizes for ZIM items (needs internet)."""
        if not online():
            return jsonify({"online": False})
        from concurrent.futures import ThreadPoolExecutor

        def size(it):
            try:
                r = kcat.resolve(it)
                return it["id"], (r["size"] if r else -1)
            except Exception:
                return it["id"], -1
        zims = [it for it in library.all_items(catalog) if it["type"] == "zim"]
        with ThreadPoolExecutor(8) as pool:
            out = dict(pool.map(size, zims))
        return jsonify({"online": True, "sizes": out})

    def queue_item(it):
        if it["type"] == "zim":
            def task(job, it=it):  # look up the newest edition in the background, then download
                r = kcat.resolve(it)
                if not r:
                    raise LookupError("not found in the Kiwix catalog")
                job.update(url=r["url"], dest=str(library.destination(it, st["cfg"], r)), total=r["size"])
                downloader._download(job)
            downloader.add_task(it["id"], it["title"], task, "zim")
        elif it["type"] in ("pdf", "text"):
            downloader.add({**it}, it["url"], library.destination(it, st["cfg"]))

    @app.post("/api/library/download")
    def lib_download():
        b = request.json or {}
        items = library.all_items(catalog)
        if b.get("tier"):
            chosen = library.items_for_tier(catalog, b["tier"], b.get("bands"))
        else:
            ids = set(b.get("ids") or [])
            chosen = [i for i in items if i["id"] in ids and i["type"] != "link"]
        chosen = [i for i in chosen if not installed.file_for(i["id"]) and
                  not (i["type"] in ("pdf", "text") and library.destination(i, st["cfg"]).exists())]
        errors = []
        for it in chosen:
            try:
                queue_item(it)
            except Exception as e:
                errors.append(str(e)[:160])
        return jsonify({"queued": len(chosen) - len(errors), "errors": errors})

    @app.post("/api/library/cancel")
    def lib_cancel():
        downloader.cancel((request.json or {}).get("id", ""))
        return jsonify({"ok": True})

    @app.get("/api/library/search")
    def lib_search():
        q = request.args.get("q", "").strip()
        if not q or not online():
            return jsonify([])
        return jsonify([{k: e[k] for k in ("title", "name", "flavour", "size", "url", "filename", "summary")}
                        for e in kcat.search(q)])

    @app.post("/api/library/add_zim")
    def lib_add_zim():
        b = request.json or {}
        it = {"id": f"custom-{b['filename']}", "type": "zim", "title": b.get("title", b["filename"])}
        downloader.add(it, b["url"], Path(st["cfg"]["zim_dir"]) / b["filename"], int(b.get("size") or 0))
        return jsonify({"queued": True})

    @app.post("/api/models/pull")
    def pull_model():
        name = (request.json or {}).get("model", "")
        if not name:
            abort(400)

        def task(job):
            for msg in st["ollama"].pull(name):
                job["detail"] = msg.get("status", "")
                if msg.get("total"):
                    job["total"], job["done"] = msg["total"], msg.get("completed", 0)
        downloader.add_task(f"model-{name}", f"AI model {name}", task, "model")
        return jsonify({"queued": True})

    # ------------------------------------------------------------ manuals & checks
    @app.post("/api/ingest")
    def ingest():
        start_ingest()
        return jsonify(st["ingest"])

    @app.post("/api/check")
    def run_check():
        if st["check"]["running"]:
            return jsonify(st["check"])

        def go():
            st["check"]["running"] = True
            try:
                st["check"]["report"] = checks.run(st["manuals"], st["kiwix"], st["ollama"], current_model(),
                                                   st["cfg"]["embed_model"], st["cfg"]["manuals_dir"])
            except Exception as e:
                st["check"]["report"] = {"passed": 0, "total": 1, "seconds": 0, "results": [
                    {"kind": "brain", "name": "Library check", "ok": False, "detail": str(e)[:200]}]}
            finally:
                st["check"]["running"] = False
        threading.Thread(target=go, daemon=True).start()
        return jsonify({"running": True})

    @app.get("/api/check")
    def get_check():
        return jsonify(st["check"])

    # ------------------------------------------------------------ readers
    @app.get("/read/kiwix/<book>/<path:path>")
    def read_kiwix(book, path):
        found = st["kiwix"].article_html(book, path)
        if not found:
            abort(404)
        content, mime = found
        resp = Response(content, mimetype=mime)
        resp.headers["Content-Security-Policy"] = "connect-src 'none'; form-action 'none'"
        return resp

    @app.get("/read/manual/<path:name>")
    def read_manual(name):
        resp = send_from_directory(st["cfg"]["manuals_dir"], name)
        if name.lower().endswith((".md", ".txt")):  # show in the browser, don't download
            resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp

    @app.get("/api/books")
    def books():
        root = Path(books_dir)
        out = []
        for p in sorted(root.rglob("*.txt")):
            out.append({"title": p.stem.replace("-", " "), "path": p.relative_to(root).as_posix(),
                        "band": p.parent.name, "size_kb": p.stat().st_size // 1024})
        return jsonify(out)

    @app.get("/read/book/<path:name>")
    def read_book(name):
        p = (Path(books_dir) / name).resolve()
        if not p.is_relative_to(Path(books_dir).resolve()) or not p.is_file():
            abort(404)
        text = p.read_text(encoding="utf-8", errors="ignore")
        # Drop Project Gutenberg's license header/footer from the reading view.
        start = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n", text)
        end = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK", text)
        body = text[start.end() if start else 0: end.start() if end else len(text)].strip()
        paras = "".join(f"<p>{html.escape(b)}</p>" for b in re.split(r"\n\s*\n", body) if b.strip())
        title = html.escape(p.stem.replace("-", " "))
        return Response(READER.replace("{{title}}", title).replace("{{body}}", paras), mimetype="text/html")

    profile_path = Path(cfg["index_path"]).parent / "household.json"

    def load_profile() -> dict:
        try:
            return json.loads(profile_path.read_text())
        except Exception:
            return {}

    @app.get("/api/profile")
    def get_profile():
        return jsonify(load_profile())

    @app.post("/api/profile")
    def save_profile():
        data = {k: str(v)[:4000] for k, v in (request.json or {}).items() if k in PROFILE_FIELDS}
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(data, indent=1))
        return jsonify({"saved": True})

    @app.get("/binder")
    def binder():
        root = Path(st["cfg"]["manuals_dir"]) / "cards"
        prof = load_profile()
        parts = []
        if any(prof.values()):
            rows = "".join(f"<tr><th>{html.escape(PROFILE_FIELDS[k])}</th><td>{html.escape(v).replace(chr(10), '<br>')}</td></tr>"
                           for k, v in prof.items() if v and k in PROFILE_FIELDS)
            parts.append(f"<section><h1>Our household</h1><table class='info'>{rows}</table></section>")
        notes = root / "BEACON-CLIFFNOTES.txt"
        if notes.exists():
            parts.append(f"<section><h1>Cliff notes</h1><pre>{html.escape(notes.read_text())}</pre></section>")
        for p in sorted(root.glob("*.md")):
            parts.append(f"<section>{mini_md(p.read_text())}</section>")
        page = BINDER.replace("{{date}}", time.strftime("%B %d, %Y")).replace("{{body}}", "".join(parts))
        return Response(page, mimetype="text/html")

    @app.get("/api/cards")
    def cards():
        root = Path(st["cfg"]["manuals_dir"]) / "cards"
        out = []
        for p in sorted(root.glob("*.md")) + sorted(root.glob("*.txt")):
            title = st["manuals"]._heading(str(p)) if p.suffix == ".md" else p.stem.replace("-", " ").title()
            out.append({"title": title, "path": f"cards/{p.name}"})
        return jsonify(out)

    app.config["downloader"] = downloader  # for tests
    app.config["installed"] = installed
    return app


def main():
    cfg = config.load()
    app = create_app(cfg)
    url = f"http://{cfg['host']}:{cfg['port']}"
    print(f"\n  Beacon is running → {url}\n  Keep this window open. Close it to quit.\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=cfg["host"], port=cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
