"""Lantern web app: a local GUI at http://127.0.0.1:8642 — no internet used."""
import json
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import config, models, rag
from .kiwix_source import KiwixLibrary
from .manuals import ManualIndex
from .ollama_client import Ollama, OllamaError

STATIC = Path(__file__).resolve().parent.parent / "static"


def create_app(cfg: dict | None = None, ollama=None, kiwix=None, manuals=None) -> Flask:
    cfg = cfg or config.load()
    app = Flask(__name__, static_folder=None)
    state = {
        "cfg": cfg,
        "ollama": ollama or Ollama(cfg["ollama_url"]),
        "kiwix": kiwix if kiwix is not None else KiwixLibrary(cfg["zim_dir"]),
        "manuals": manuals,
        "ingest": {"running": False, "log": []},
    }
    if state["manuals"] is None:
        state["manuals"] = ManualIndex(cfg["index_path"], state["ollama"], cfg["embed_model"])

    def current_model() -> str | None:
        installed = state["ollama"].models()
        wanted = state["cfg"].get("chat_model")
        if wanted and any(models._same(wanted, m) for m in installed):
            return wanted
        return models.best_model(installed)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name)

    @app.get("/api/status")
    def status():
        o = state["ollama"]
        up = o.is_up()
        installed = o.models() if up else []
        return jsonify({
            "ollama": up,
            "model": current_model() if up else None,
            "models": [m for m in installed if "embed" not in m],
            "ram_gb": round(models.system_ram_gb(), 1),
            "books": state["kiwix"].summary(),
            "manuals": state["manuals"].files(),
            "ingest": state["ingest"],
        })

    @app.post("/api/model")
    def set_model():
        name = (request.json or {}).get("model", "")
        state["cfg"]["chat_model"] = name
        config.save({"chat_model": name})
        return jsonify({"model": name})

    @app.post("/api/ask")
    def ask():
        body = request.json or {}
        question = (body.get("question") or "").strip()
        if not question:
            abort(400, "empty question")
        history = body.get("history") or []
        use_library = body.get("use_library", True)

        def stream():
            def event(kind, data):
                return f"event: {kind}\ndata: {json.dumps(data)}\n\n"
            sources = []
            if use_library:
                yield event("status", "Searching your library…")
                sources = rag.gather(question, state["kiwix"], state["manuals"], state["cfg"])
            yield event("sources", [{k: s[k] for k in ("kind", "book", "title", "ref")} for s in sources])
            model = current_model()
            if not model:
                yield event("error", "No model found. Run the setup script to download one.")
                return
            yield event("status", f"Thinking with {model}…")
            try:
                for piece in rag.answer(question, sources, history, state["ollama"], model):
                    yield event("token", piece)
            except OllamaError as e:
                yield event("error", str(e))
            yield event("done", model)

        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/ingest")
    def ingest():
        if state["ingest"]["running"]:
            return jsonify(state["ingest"])

        def run():
            st = state["ingest"]
            st.update(running=True, log=[])
            try:
                res = state["manuals"].ingest_dir(state["cfg"]["manuals_dir"],
                                                  progress=lambda m: st["log"].append(m))
                st["log"].append(f"Done: {res['indexed']} new/changed, "
                                 f"{res['unchanged']} unchanged, {res['total_chunks']} passages.")
            except Exception as e:
                st["log"].append(f"Error: {e}")
            finally:
                st["running"] = False

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"running": True})

    @app.get("/read/kiwix/<book>/<path:path>")
    def read_kiwix(book, path):
        found = state["kiwix"].article_html(book, path)
        if not found:
            abort(404)
        content, mime = found
        return Response(content, mimetype=mime)

    @app.get("/read/manual/<path:name>")
    def read_manual(name):
        resp = send_from_directory(state["cfg"]["manuals_dir"], name)
        if name.lower().endswith((".md", ".txt")):  # show in the browser, don't download
            resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp

    return app


def main():
    cfg = config.load()
    app = create_app(cfg)
    url = f"http://{cfg['host']}:{cfg['port']}"
    print(f"\n  Lantern is running → {url}\n  Keep this window open. Close it to quit.\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=cfg["host"], port=cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
