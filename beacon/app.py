"""Beacon web app: a local GUI at http://127.0.0.1:8642. Works with no internet."""
import argparse
import html
import io
import json
import logging
import os
import re
import signal
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, abort, jsonify, redirect, request, send_file, send_from_directory

from . import checks, config, library, mapdata, models, plans, rag, system
from .archive import Archive
from .board import Board
from .mesh import MeshBridge, serial_ports
from .audit import Audit, describe, nearby_devices
from .pdf import markdown_pdf
from .share import Share, allowed_host, is_local, lan_ip
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
<section class="cover"><h1>BEACON</h1><p>Emergency binder, printed {{date}}</p><p>Keep with your emergency supplies.</p></section>
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


ARCHIVE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title><style>
body{font:18px/1.6 Charter,"Iowan Old Style",Georgia,serif;color:#111;background:#fff;max-width:720px;margin:0 auto;padding:28px 20px 60px}
h1,h2,h3{font-family:"DIN Alternate",-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.2}h1{font-size:30px;margin:0 0 4px}
.meta{color:#555;font-size:15px;margin:0 0 18px}.bar{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 26px}
.bar a,.bar button{font:700 15px "DIN Alternate",-apple-system,sans-serif;padding:9px 14px;border-radius:8px;border:1px solid #bbb;background:#f2f4f6;color:#111;text-decoration:none;cursor:pointer}
table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}
.sources{border-top:1px dashed #bbb;margin-top:24px;padding-top:8px;font-size:15px;color:#444}
@media print{.bar{display:none}}</style></head><body>
<h1>{{title}}</h1><p class="meta">{{meta}}</p>
<div class="bar"><a href="{{pdf}}" download>Download PDF</a><button onclick="print()">Print</button><a href="/">Open Beacon</a></div>
{{body}}{{sources}}</body></html>"""

JOIN = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Join Beacon</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F1A24;color:#E6EDF2;font:18px/1.5 "DIN Alternate",-apple-system,sans-serif}
form{width:min(340px,90vw);text-align:center} h1{font-size:30px;margin:0 0 6px} p{color:#8FA3B3;margin:0 0 22px}
input{font:inherit;font-size:34px;letter-spacing:12px;text-align:center;width:100%;padding:12px;border-radius:12px;border:1px solid #24394A;background:#152330;color:#E6EDF2;box-sizing:border-box}
button{margin-top:14px;width:100%;font:inherit;padding:14px;border:0;border-radius:12px;background:#FF5A1F;color:#1A0A00;font-weight:700}
.err{color:#FF8A65;min-height:1.5em}
</style></head><body><form method="get" action="/"><h1>Beacon</h1><p>{{msg}}</p>
<input name="code" inputmode="numeric" maxlength="4" autocomplete="one-time-code" autofocus><div class="err">{{err}}</div><button>Join</button></form></body></html>"""

GUEST_COOKIE = "beacon_guest"

# Content-Security-Policy for Beacon's own pages: only Beacon's own scripts, and pages can
# only talk back to Beacon. Even if something slipped through, there's nowhere to send data.
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; child-src 'self' blob:; frame-src 'self'; "
           "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
# Printable pages (binder, book reader) carry a few inline buttons and nothing else.
PRINT_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; "
             "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
# Pages from downloaded Kiwix libraries are third-party content: no scripts, and a sandbox
# that gives them a throwaway origin, so they can never read Beacon's data.
LIBRARY_CSP = ("sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'self' data: blob:; script-src 'none'; "
               "style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'self'; frame-ancestors 'self'")
SAFE_INLINE = (".pdf", ".md", ".txt")  # anything else in the manuals folder downloads instead of opening

# Guests on the Wi-Fi can use Beacon but not change it.
GUEST_BLOCKED = ("/api/library/download", "/api/library/cancel", "/api/library/add_zim", "/api/models/pull",
                 "/api/maps/build", "/api/ingest", "/api/profile", "/api/model", "/api/quit", "/api/share",
                 "/api/power", "/api/library/sizes", "/api/security", "/api/mesh/connect", "/api/mesh/disconnect",
                 "/api/mesh/settings", "/api/supplies")


def sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


def create_app(cfg: dict | None = None, ollama=None, kiwix=None, manuals=None, http=None) -> Flask:
    cfg = cfg or config.load()
    data_root = cfg.get("data_root") or str(Path(cfg["zim_dir"]).parent.parent)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # questions and forms are small
    o = ollama or Ollama(cfg["ollama_url"])
    st = {
        "cfg": cfg, "ollama": o,
        "kiwix": kiwix if kiwix is not None else KiwixLibrary(cfg["zim_dir"]),
        "manuals": manuals if manuals is not None else ManualIndex(cfg["index_path"], o, cfg["embed_model"], cfg["manuals_dir"]),
        "places": Places(str(mapdata.maps_dir(data_root) / "places.tsv")),
        "ingest": {"running": False, "log": []},
        "check": {"running": False, "report": None},
        "online": {"at": 0, "value": False},
        "low_power": False,
    }
    http_mod = http or library.requests
    catalog = library.load_catalog()
    kcat = library.KiwixCatalog(str(Path(cfg["index_path"]).parent / "kiwix_catalog.json"), http_mod)
    installed = library.Installed(str(Path(cfg["index_path"]).parent / "installed.json"), data_root)
    integrity = library.Integrity(str(Path(cfg["index_path"]).parent / "integrity.json"), data_root)
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
                z = st["manuals"].ingest_zim_pdfs(st["kiwix"], progress=lambda m: log["log"].append(m))
                res["total_chunks"] = z["total_chunks"]
                log["log"].append(f"Done: {res['indexed']} new/changed, {res['unchanged']} unchanged, "
                                  f"{res['total_chunks']:,} passages searchable.")
            except Exception as e:
                log["log"].append(f"Error: {e}")
            finally:
                log["running"] = False
                ingest_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def manual_titles() -> dict:
        """Downloaded manuals are shown by their catalog title, not their file name."""
        out, root = {}, Path(st["cfg"]["manuals_dir"])
        for it in library.all_items(catalog):
            f = installed.file_for(it["id"])
            if not f and it["type"] in ("pdf", "text", "page") and not it.get("files"):
                p = library.destination(it, st["cfg"])
                f = str(p) if p.exists() else None
            if not f:
                continue
            p = Path(f)
            for sub in (sorted(p.iterdir()) if p.is_dir() else [p]):
                try:
                    rel = sub.relative_to(root).as_posix()
                except ValueError:
                    continue
                out[rel] = f"{it['title']}: {re.sub(r'[-_]+', ' ', sub.stem)}" if p.is_dir() else it["title"]
        return out

    def on_download_done(job):
        try:
            st["manuals"].display = manual_titles()
        except Exception:
            pass
        if job["type"] == "zim":
            st["kiwix"].reload(st["cfg"]["zim_dir"])
            threading.Timer(1.0, start_ingest).start()  # index any PDFs packed inside it
        elif job["type"] in ("pdf", "text", "page") and not str(job.get("dest", "")).startswith(books_dir):
            threading.Timer(1.0, start_ingest).start()
        elif job["type"] == "places":
            st["places"] = Places(str(mapdata.maps_dir(data_root) / "places.tsv"))

    downloader = library.Downloader(installed, on_done=on_download_done, http=http_mod, integrity=integrity)
    try:
        st["manuals"].display = manual_titles()
    except Exception:
        pass

    def online() -> bool:
        if guest():  # only the Beacon computer's own visits check the internet
            return st["online"]["value"]
        if time.time() - st["online"]["at"] > 60:
            st["online"] = {"at": time.time(), "value": library.is_online(http_mod)}
        return st["online"]["value"]

    share = Share(app)
    app.config["share"] = share
    audit = Audit(str(Path(data_root) / "data" / "logs" / "security.log"))
    app.config["audit"] = audit
    archive = Archive(str(Path(data_root) / "data" / "archive"))
    app.config["archive"] = archive
    board = Board(str(Path(data_root) / "data" / "board.json"))
    mesh = MeshBridge(board, audit)
    app.config["board"], app.config["mesh"] = board, mesh
    guest_writes: dict[tuple, list[float]] = {}

    def guest_rate_ok(key: str, limit: int, seconds: int) -> bool:
        """Guests can post and save, but not flood the drive."""
        now, k = time.time(), (key, request.remote_addr)
        recent = [t for t in guest_writes.get(k, []) if now - t < seconds]
        guest_writes[k] = recent
        if len(recent) >= limit:
            return False
        recent.append(now)
        return True

    def guest() -> bool:
        return not is_local(request.remote_addr)

    def join_page(err: str):
        msg = ("Enter the 4-digit code shown on the Beacon computer." if share.on else
               "Beacon isn't shared right now. Ask whoever is running it to click Share.")
        page = JOIN.replace("{{msg}}", html.escape(msg, quote=False)).replace("{{err}}", html.escape(err, quote=False))
        return Response(page, mimetype="text/html", status=401)

    @app.before_request
    def guard():
        ip, ua = request.remote_addr or "?", request.headers.get("User-Agent", "")
        # 1. Only answer to Beacon's own names. Blocks DNS rebinding from other websites.
        if not allowed_host(request.host):
            audit.add("rejected-host", ip, ua, f"Reached Beacon through the name {request.host[:60]!r}, which Beacon "
                      "doesn't answer to. Web pages use this trick (DNS rebinding) to read local apps.", "alert")
            return Response("Beacon doesn't answer to this address.", status=403, mimetype="text/plain")
        # 2. Anything that changes something needs a header other websites can't send (CSRF).
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith("/api/"):
            origin = request.headers.get("Origin")
            if request.headers.get("X-Beacon") != "1" or (origin and urlparse(origin).netloc.lower() != request.host.lower()):
                audit.add("blocked-request", ip, ua, f"Tried {request.path} without Beacon's own header"
                          + (f" from {origin[:60]}" if origin else "") + ". Usually another website.", "alert")
                return jsonify({"error": "Blocked: that request didn't come from Beacon."}), 403
        if not guest():
            return None
        # 3. Guests on the Wi-Fi: the code once (rate limited), then a random session token.
        code = request.args.get("code")
        if code is not None:
            ok, msg, event = share.check_code(ip, code)
            if ok:
                resp = redirect(request.path or "/")
                resp.set_cookie(GUEST_COOKIE, share.new_token(ip, ua), max_age=7 * 86400, httponly=True, samesite="Lax")
                audit.add("signed-in", ip, ua, "Signed in with the code")
                return resp
            if event == "wrong":
                audit.add("wrong-code", ip, ua, "Entered a wrong code", "warn")
            elif event == "locked":
                audit.add("locked-out", ip, ua, "Locked out for 5 minutes after 5 wrong codes", "alert")
            elif event == "still-locked":
                audit.add("locked-out", ip, ua, "Kept trying codes while locked out", "alert")
            elif event == "rotated":
                audit.add("code-changed", ip, ua, "Too many wrong codes from several devices, so Beacon changed the code", "alert")
            return join_page(msg)
        token = request.cookies.get(GUEST_COOKIE)
        if not share.valid(token):
            if request.path == "/" or request.path.startswith("/api/"):
                audit.add("visit", ip, ua, "Opened Beacon without signing in" if share.on else
                          "Tried to open Beacon while Wi-Fi sharing was off")
            if request.path.startswith("/api/"):
                return jsonify({"error": "Enter the Beacon code first"}), 401
            return join_page("")
        share.touch(token, ip, ua)
        if request.path.startswith(GUEST_BLOCKED):
            audit.add("host-only", ip, ua, f"Tried a host-only action ({request.path})", "warn")
            return jsonify({"error": "Only the Beacon computer can do that."}), 403
        return None

    @app.after_request
    def security_headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        if not guest():
            h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=(), usb=(), geolocation=(self)")
        if resp.mimetype == "text/html" and "Content-Security-Policy" not in h:
            h["Content-Security-Policy"] = APP_CSP
        if request.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return resp

    # ------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/api/ping")
    def ping():
        return jsonify({"ok": True, "guest": guest()})

    @app.post("/api/quit")
    def quit_beacon():
        """Stop Beacon and the AI engine it started, so the drive can be ejected."""
        share.stop()
        pidfile = Path(data_root) / "data" / "run" / "ollama.pid"

        def stop():
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                pidfile.unlink()
            except Exception:
                pass
            os._exit(0)
        threading.Timer(0.6, stop).start()
        return jsonify({"stopping": True})

    @app.get("/api/share")
    def share_status():
        return jsonify(share.status())

    @app.post("/api/share")
    def share_toggle():
        on = bool((request.json or {}).get("on"))
        was = share.on
        res = share.start() if on else share.stop()
        if on and res["on"] and not was:
            audit.add("sharing-on", "127.0.0.1", "", f"Wi-Fi sharing turned on at {res.get('name_url') or res.get('ip_url')}")
        elif not on and was:
            audit.add("sharing-off", "127.0.0.1", "", "Wi-Fi sharing turned off; every device was signed out")
        return jsonify(res)

    @app.post("/api/share/signout")
    def share_signout():
        n = len(share.tokens)
        res = share.sign_out_all()
        audit.add("signed-out-all", "127.0.0.1", "", f"Signed out {n} device(s) and changed the code")
        return jsonify(res)

    @app.post("/api/share/revoke")
    def share_revoke():
        gone = share.revoke(str((request.json or {}).get("id", "")))
        if gone:
            audit.add("signed-out", gone["ip"], gone["ua"], "Signed out by the Beacon computer")
        return jsonify({"revoked": bool(gone), **share.status()})

    def session_view(sess):
        return {**{k: sess[k] for k in ("id", "ip", "since", "last", "hits", "active")},
                "device": describe(sess["ua"]), "mac": audit.mac_for(sess["ip"])}

    @app.get("/api/security")
    def security_view():
        out = {"sharing": share.status(), "sessions": [session_view(x) for x in share.sessions()],
               "events": audit.since(0, 100), "unseen": audit.unseen, "last": audit.seq}
        if request.args.get("devices") == "1":
            signed = {x["ip"] for x in share.sessions()}
            out["devices"] = [{**d, "signed_in": d["ip"] in signed} for d in nearby_devices()]
        return jsonify(out)

    @app.get("/api/security/events")
    def security_events():
        after = int(request.args.get("after", 0) or 0)
        return jsonify({"events": audit.since(after), "unseen": audit.unseen, "last": audit.seq,
                        "guests": len(share.tokens), "sharing": share.on})

    @app.post("/api/security/seen")
    def security_seen():
        audit.mark_seen()
        return jsonify({"unseen": 0})

    @app.get("/api/security/log.csv")
    def security_csv():
        resp = Response(audit.csv(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f'attachment; filename="Beacon-security-log-{time.strftime("%Y-%m-%d")}.csv"'
        return resp

    @app.post("/api/power")
    def power():
        st["low_power"] = bool((request.json or {}).get("low"))
        if st["low_power"]:
            m = current_model()
            if m:
                threading.Thread(target=lambda: st["ollama"].unload(m), daemon=True).start()
        return jsonify({"low": st["low_power"]})

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
        rep["low_power"] = st["low_power"]
        rep["guest"] = guest()
        rep["sharing"] = share.on
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
    def stream_answer(question, retrieval_query, history, use_library, extra_sources=(), card_hint=None, save=None):
        prof = models.profile()
        card = rag.match_card(card_hint or question)
        if card and (Path(st["cfg"]["manuals_dir"]) / "cards" / card).exists():
            title = st["manuals"]._heading(f"cards/{card}")
            yield sse("card", {"file": card, "title": title})
        if st["low_power"]:
            yield sse("error", "Low power mode is on, so the AI is off to save battery. The quick cards, Tools, "
                               "Map and Library still work. Turn low power off to ask the AI.")
            yield sse("done", "")
            return
        yield sse("status", "Searching your library…")
        sources = list(extra_sources)
        if use_library:
            sources += rag.gather(retrieval_query, st["kiwix"], st["manuals"], prof)
        yield sse("sources", [{k: s.get(k, "") for k in ("kind", "book", "title", "ref", "page")} for s in sources])
        model = current_model()
        if not model:
            yield sse("error", "No AI model is installed. Open the Library tab → Brain to download one.")
            return
        yield sse("status", f"Thinking with {model} ({prof['name']} brain)…")
        parts = []
        try:
            for piece in rag.answer(question, sources, history, st["ollama"], model, prof["num_ctx"]):
                parts.append(piece)
                yield sse("token", piece)
        except OllamaError as e:
            yield sse("error", str(e))
        text = re.sub(r"<think>.*?(</think>|$)", "", "".join(parts), flags=re.S).strip()
        if save and text:  # plans are kept in the archive, readable later with the AI off
            item = archive.save(markdown=text, sources=[{k: x.get(k, "") for k in ("kind", "book", "title", "ref", "page")}
                                                        for x in sources], **save)
            yield sse("saved", {"id": item["id"], "shared": item["shared"]})
        yield sse("done", model)

    def sse_response(gen):
        return Response(gen, mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/ask")
    def ask():
        body = request.json or {}
        q = (body.get("question") or "").strip()[:4000]
        if not q:
            abort(400, "empty question")
        history = [{"role": h.get("role"), "content": str(h.get("content", ""))[:8000]}
                   for h in (body.get("history") or [])[-6:] if isinstance(h, dict)]
        return sse_response(stream_answer(q, q, history, body.get("use_library", True)))

    @app.post("/api/translate")
    def translate():
        body = request.json or {}
        text, to = (body.get("text") or "").strip()[:4000], (body.get("to") or "").strip()[:40]
        if not text or not to:
            abort(400)

        def gen():
            if st["low_power"]:
                yield sse("error", "Low power mode is on, so the AI is off. Turn it off to translate.")
                yield sse("done", ""); return
            model = current_model()
            if not model:
                yield sse("error", "No AI model is installed."); return
            msgs = [{"role": "system", "content": "You translate text for travelers in difficult situations. "
                     "Reply with only the translation, in simple everyday words. If a phrase could be "
                     "misunderstood, add a short note in brackets after it."},
                    {"role": "user", "content": f"Translate into {to}:\n\n{text}"}]
            try:
                for piece in st["ollama"].chat_stream(model, msgs, options={"num_ctx": 4096}):
                    yield sse("token", piece)
            except OllamaError as e:
                yield sse("error", str(e))
            yield sse("done", model)
        return sse_response(gen())

    @app.get("/api/plans")
    def plan_list():
        return jsonify(plans.public_list())

    @app.post("/api/plan")
    def make_plan():
        body = request.json or {}
        tpl = plans.get(body.get("template", ""))
        if not tpl:
            abort(404)
        answers = {str(k)[:40]: str(v)[:2000] for k, v in dict(body.get("answers") or {}).items()}
        prof = {} if guest() else load_profile()  # My Info fills in what the form left blank (host only)
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
        save = None if guest() else {"kind": "plan", "title": tpl["title"], "shared": False, "by": "host",
                                     "meta": {"template": tpl["id"], "location": answers.get("location", ""),
                                              "phase": answers.get("phase", "")}}
        return sse_response(stream_answer(instruction, query, [], True, card_hint=tpl["title"] + " " + tpl["search"], save=save))

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
        if not f and it["type"] in ("pdf", "text", "page") and not it.get("files"):
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
            "gear_list": catalog.get("gear_list", {}),
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
        library.queue_item(it, downloader, kcat, st["cfg"], http_mod)

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
                  not (i["type"] in ("pdf", "text", "page") and library.destination(i, st["cfg"]).exists())]
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
        if not str(b.get("url", "")).startswith("https://") or not re.fullmatch(r"\w[\w.\-]*\.zim", b["filename"]):
            abort(400)
        downloader.add(it, b["url"], Path(st["cfg"]["zim_dir"]) / b["filename"], int(b.get("size") or 0),
                       sha256_url=b["url"] + ".sha256")
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
                rep = checks.run(st["manuals"], st["kiwix"], st["ollama"], current_model(),
                                 st["cfg"]["embed_model"], st["cfg"]["manuals_dir"])
                rep["results"] += checks.security(st["cfg"], system.drive_info(data_root), integrity, share.status(),
                                                  audit.failures_since(24 * 3600), lan_ip())
                rep["passed"] = sum(r["ok"] for r in rep["results"])
                rep["total"] = len(rep["results"])
                st["check"]["report"] = rep
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

    # ------------------------------------------------------------ community board & mesh
    @app.get("/api/board")
    def board_view():
        return jsonify({"posts": board.view(for_guest=guest()), "roster": board.roster(), "mesh": mesh.status(),
                        "me": request.remote_addr if guest() else "host"})

    @app.post("/api/board")
    def board_post():
        b = request.json or {}
        text, kind = str(b.get("text") or "").strip(), str(b.get("kind") or "note")
        if kind != "checkin" and not text:
            abort(400)
        if kind == "checkin" and not str(b.get("name") or "").strip():
            return jsonify({"error": "Add a name so people know who checked in."}), 400
        if guest() and not guest_rate_ok("board", 12, 600):
            return jsonify({"error": "That's a lot of posts. Wait a few minutes and try again."}), 429
        ua = request.headers.get("User-Agent", "")
        post = board.add(kind, text, name=b.get("name", ""), status=b.get("status", ""),
                         ip=request.remote_addr or "", device=describe(ua) if guest() else "This Mac")
        if b.get("mesh") and mesh.state == "connected" and (not guest() or mesh.allow_guests):
            line = (f"{'SAFE' if post['status'] == 'safe' else 'HELP'} {post['name']}" + (f": {post['text']}" if post["text"] else "")
                    if kind == "checkin" else (f"{post['name']}: " if post["name"] else "") + post["text"])
            channel = str(b.get("channel") or 0)
            if mesh.send(line, int(channel) if channel.isdigit() and int(channel) < 8 else 0):  # radios have channels 0-7
                board.update(post["id"], sent_mesh=True)
                post["sent_mesh"] = True
        return jsonify({k: v for k, v in post.items() if k not in ("ip",)})

    @app.post("/api/board/resolve")
    def board_resolve():
        p = board.find(str((request.json or {}).get("id", "")))
        if not p:
            abort(404)
        if guest() and p["ip"] != request.remote_addr:
            return jsonify({"error": "Only the person who posted it, or the Beacon computer, can mark it resolved."}), 403
        now_resolved = not p["resolved"]
        board.update(p["id"], resolved=now_resolved)
        return jsonify({"resolved": now_resolved})

    @app.post("/api/board/pin")
    def board_pin():
        if guest():
            abort(403)
        p = board.update(str((request.json or {}).get("id", "")), pinned=bool((request.json or {}).get("pinned")))
        return jsonify({"pinned": bool(p and p["pinned"])})

    @app.post("/api/board/remove")
    def board_remove():
        if guest():
            abort(403)
        return jsonify({"removed": board.remove(str((request.json or {}).get("id", "")))})

    @app.get("/api/mesh")
    def mesh_view():
        out = {**mesh.status(), "nodes_list": mesh.nodes()}
        if not guest():
            out["ports"] = serial_ports()
        return jsonify(out)

    @app.post("/api/mesh/connect")
    def mesh_connect():
        b = request.json or {}
        host = (b.get("host") or "").strip() or None
        if host and not re.fullmatch(r"[\w.\-:]+", host):
            abort(400)
        mesh.connect(port=(b.get("port") or None), host=host)
        return jsonify(mesh.status())

    @app.post("/api/mesh/disconnect")
    def mesh_disconnect():
        mesh.disconnect()
        return jsonify(mesh.status())

    @app.post("/api/mesh/settings")
    def mesh_settings():
        mesh.allow_guests = bool((request.json or {}).get("allow_guests"))
        return jsonify(mesh.status())

    # ------------------------------------------------------------ archive & PDFs
    def with_sources(md: str, sources) -> str:
        rows = []
        for i, x in enumerate((sources or [])[:40], 1):
            if isinstance(x, dict) and x.get("book"):
                extra = f", {x['title']}" if x.get("title") and x.get("title") != x.get("book") else ""
                rows.append(f"{i}. {x['book']}{extra}")
        return md.rstrip() + ("\n\n## Sources\n\n" + "\n".join(rows) if rows else "")

    def file_title(title: str) -> str:
        plain = re.sub(r"[^\w .,()'-]+", " ", title).encode("ascii", "ignore").decode()
        return re.sub(r"\s+", " ", "Beacon - " + plain).strip()[:90]

    def pdf_response(title: str, md: str, meta: str):
        resp = Response(markdown_pdf(title, md, meta), mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="{file_title(title)}.pdf"'
        return resp

    def item_meta(it: dict) -> str:
        when = time.strftime("%B %d, %Y", time.localtime(it.get("created", time.time())))
        bits = [it["meta"].get("location", "")] if it.get("meta") else []
        return ", ".join([b for b in bits if b] + [when])

    def visible(it) -> bool:
        return bool(it) and (not guest() or it.get("shared"))

    @app.post("/api/pdf")
    def make_pdf():
        b = request.json or {}
        md = str(b.get("markdown") or "")[:120_000]
        if not md.strip():
            abort(400)
        title = str(b.get("title") or "Beacon")[:200]
        return pdf_response(title, with_sources(md, b.get("sources")), str(b.get("meta") or "")[:300])

    @app.get("/api/archive")
    def archive_list():
        return jsonify(archive.list(shared_only=guest()))

    @app.post("/api/archive")
    def archive_save():
        b = request.json or {}
        if not str(b.get("markdown") or "").strip():
            abort(400)
        if guest():
            if not guest_rate_ok("archive", 10, 3600):
                return jsonify({"error": "This device has shared a lot already. Try again later."}), 429
            item = archive.save(b.get("kind", "answer"), b.get("title", ""), b["markdown"], b.get("sources"), b.get("meta"),
                                shared=True, by="guest", device=describe(request.headers.get("User-Agent")))
        else:
            item = archive.save(b.get("kind", "answer"), b.get("title", ""), b["markdown"], b.get("sources"), b.get("meta"),
                                shared=bool(b.get("shared")), by="host")
        return jsonify({k: item[k] for k in ("id", "kind", "title", "created", "shared")})

    @app.get("/api/archive/<item_id>")
    def archive_get(item_id):
        it = archive.get(item_id)
        if not visible(it):
            abort(404)
        return jsonify(it)

    @app.post("/api/archive/<item_id>/share")
    def archive_share(item_id):
        if guest():
            abort(403)
        it = archive.set_shared(item_id, bool((request.json or {}).get("shared")))
        if not it:
            abort(404)
        return jsonify({"id": it["id"], "shared": it["shared"]})

    @app.post("/api/archive/<item_id>/delete")
    def archive_delete(item_id):
        if guest():
            abort(403)
        return jsonify({"deleted": archive.delete(item_id)})

    @app.get("/archive/<name>")
    def archive_page(name):
        """A saved plan or answer as its own page (or PDF), for phones on the Wi-Fi."""
        item_id = name[:-4] if name.endswith(".pdf") else name
        it = archive.get(item_id)
        if not visible(it):
            abort(404)
        if name.endswith(".pdf"):
            return pdf_response(it["title"], with_sources(it["markdown"], it["sources"]), item_meta(it))
        srcs = "".join(f"<li>{html.escape(x.get('book', ''))}{(', ' + html.escape(x['title'])) if x.get('title') and x.get('title') != x.get('book') else ''}</li>"
                       for x in it["sources"] if x.get("book"))
        page = (ARCHIVE_PAGE.replace("{{title}}", html.escape(it["title"])).replace("{{meta}}", html.escape(item_meta(it)))
                .replace("{{pdf}}", f"/archive/{it['id']}.pdf").replace("{{body}}", mini_md(it["markdown"]))
                .replace("{{sources}}", f"<div class='sources'><h3>Sources</h3><ol>{srcs}</ol></div>" if srcs else ""))
        resp = Response(page, mimetype="text/html")
        resp.headers["Content-Security-Policy"] = PRINT_CSP
        return resp

    # ------------------------------------------------------------ readers
    @app.get("/read/kiwix/<book>/<path:path>")
    def read_kiwix(book, path):
        found = st["kiwix"].article_html(book, path)
        if not found:
            abort(404)
        content, mime = found
        if "javascript" in mime or "ecmascript" in mime:
            mime = "text/plain"  # library pages can't run scripts, so never serve their scripts as runnable either
        resp = Response(content, mimetype=mime)
        if any(k in mime for k in ("html", "svg", "xml")):
            resp.headers["Content-Security-Policy"] = LIBRARY_CSP
        return resp

    @app.get("/read/manual/<path:name>")
    def read_manual(name):
        dl = request.args.get("download") == "1" or not name.lower().endswith(SAFE_INLINE)
        resp = send_from_directory(st["cfg"]["manuals_dir"], name, as_attachment=dl)
        if name.lower().endswith((".md", ".txt")) and not dl:  # show in the browser
            resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp

    @app.get("/download/cards.zip")
    def cards_zip():
        """Every quick card, the cliff notes and the start guide, for saving to a phone."""
        root = Path(st["cfg"]["manuals_dir"]) / "cards"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.glob("*")):
                if p.suffix in (".md", ".txt"):
                    z.write(p, f"Beacon cards/{p.name}")
            start = Path(data_root) / "START-HERE.txt"
            if start.exists():
                z.write(start, "Beacon cards/START-HERE.txt")
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="Beacon-cards.zip")

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
        if request.args.get("download") == "1":
            return send_file(p, as_attachment=True, download_name=p.name)
        title = html.escape(p.stem.replace("-", " "))
        resp = Response(READER.replace("{{title}}", title).replace("{{body}}", paras), mimetype="text/html")
        resp.headers["Content-Security-Policy"] = PRINT_CSP
        return resp

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

    supplies_path = Path(cfg["index_path"]).parent / "supplies.json"

    @app.get("/api/supplies")
    def get_supplies():
        try:
            return jsonify(json.loads(supplies_path.read_text()))
        except Exception:
            return jsonify({"people": 2, "items": []})

    @app.post("/api/supplies")
    def save_supplies():
        b = request.json or {}
        try:
            people = max(1, min(500, int(b.get("people", 2))))
        except (TypeError, ValueError):
            abort(400)
        items = []
        for it in (b.get("items") or [])[:500]:
            if not isinstance(it, dict):
                continue
            def num(k):
                try:
                    return max(0.0, min(1e7, float(it.get(k) or 0)))
                except (TypeError, ValueError):
                    return 0.0
            items.append({"id": str(it.get("id", ""))[:20], "cat": str(it.get("cat", "other"))[:20],
                          "name": str(it.get("name", ""))[:80], "qty": num("qty"), "unit": str(it.get("unit", ""))[:20],
                          "kcal": num("kcal"), "gal": num("gal"), "expires": str(it.get("expires", ""))[:10]})
        supplies_path.parent.mkdir(parents=True, exist_ok=True)
        supplies_path.write_text(json.dumps({"people": people, "items": items}, indent=1))
        return jsonify({"saved": True, "people": people, "items": len(items)})

    @app.post("/api/profile/erase")
    def erase_profile():
        """Remove the household info from the drive. (On flash drives the old bytes may linger
        until they're overwritten; an encrypted drive is the real protection.)"""
        if profile_path.exists():
            try:
                with open(profile_path, "r+b") as f:
                    f.write(b"\0" * max(1, profile_path.stat().st_size))
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass
            profile_path.unlink()
        return jsonify({"erased": True})

    @app.get("/binder")
    def binder():
        root = Path(st["cfg"]["manuals_dir"]) / "cards"
        prof = load_profile()
        parts = []
        if guest():
            prof = {}
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
        resp = Response(page, mimetype="text/html")
        resp.headers["Content-Security-Policy"] = PRINT_CSP
        if request.args.get("download") == "1":
            resp.headers["Content-Disposition"] = 'attachment; filename="Beacon-binder.html"'
        return resp

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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="beacon")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    a = ap.parse_args(argv)
    cfg = config.load()
    app = create_app(cfg)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # no request log: it would record searches and codes
    url = f"http://{cfg['host']}:{cfg['port']}"
    print(f"\n  Beacon is running at {url}\n  Use Quit in Beacon (or close this window) to stop it.\n")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=cfg["host"], port=cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
