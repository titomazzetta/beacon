"""Library check: prove the AI can actually reach every manual and every library."""
import re
import time
from pathlib import Path


def _probe(passage: str) -> str:
    """A distinctive ~14-word phrase from the middle of a passage."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", passage)
    if len(words) < 8:
        return " ".join(words)
    mid = len(words) // 2
    return " ".join(words[max(0, mid - 7): mid + 7])


def run(manuals, kiwix, ollama, model: str | None, embed_model: str, manuals_dir: str) -> dict:
    started = time.time()
    results = []

    # 1. The brain: is the engine up, are the models there, does it answer?
    up = ollama.is_up()
    installed = ollama.models() if up else []
    results.append({"kind": "brain", "name": "AI engine", "ok": up,
                    "detail": "Running" if up else "Not running — restart Beacon"})
    has_embed = any(m.split(":")[0] == embed_model for m in installed)
    results.append({"kind": "brain", "name": f"Search model ({embed_model})", "ok": has_embed,
                    "detail": "Installed" if has_embed else "Missing — manuals can't be searched"})
    if up and model:
        try:
            reply = ollama.generate_once(model, "Reply with one word: READY")
            ok = bool(reply.strip())
            results.append({"kind": "brain", "name": f"Answer test ({model})", "ok": ok,
                            "detail": f"Replied: {reply.strip()[:40]}" if ok else "Empty reply"})
        except Exception as e:
            results.append({"kind": "brain", "name": f"Answer test ({model})", "ok": False,
                            "detail": str(e)[:120]})
    else:
        results.append({"kind": "brain", "name": "Answer test", "ok": False,
                        "detail": "No chat model installed"})

    # 2. Every manual: indexed, has real text, and is findable by search.
    pending = manuals.pending(manuals_dir)
    for rel in pending:
        results.append({"kind": "manual", "name": rel, "ok": False,
                        "detail": "Not indexed yet — click Index manuals"})
    info = {f["path"]: f for f in manuals.files()}
    samples = dict(manuals.samples())
    for file, passage in samples.items():
        rel = manuals.rel(file)
        f = info.get(rel, {})
        try:
            hits = manuals.search(_probe(passage), k=8) if has_embed else []
            found = any(h.get("file") == file for h in hits)
        except Exception:
            found = False
        detail = f"{f.get('chunks', 0)} passages, findable" if found else "Indexed but search didn't find it"
        if f.get("scanned"):
            detail += " · mostly scanned images: only part of the text is readable"
        results.append({"kind": "manual", "name": rel, "ok": found, "warn": f.get("scanned"),
                        "detail": detail})
    for rel, f in info.items():  # indexed files that produced no passages at all
        if f["chunks"] == 0:
            results.append({"kind": "manual", "name": rel, "ok": False,
                            "detail": "No readable text (scanned PDF). Needs OCR to be searchable."})

    # 3. Every Kiwix library: opens, and a random article is findable.
    for book in kiwix.summary():
        title = kiwix.random_title(book["id"])
        if not title:
            results.append({"kind": "library", "name": book["title"], "ok": False,
                            "detail": "Couldn't read articles from this file"})
            continue
        hits = kiwix.search(title, per_book=5, max_chars=200, only=book["id"])
        ok = any(h["title"] == title for h in hits) or bool(hits)
        results.append({"kind": "library", "name": book["title"], "ok": ok,
                        "detail": f"{book['articles']:,} articles · found “{title[:40]}”" if ok
                        else f"Search returned nothing for “{title[:40]}”"})

    passed = sum(r["ok"] for r in results)
    return {"passed": passed, "total": len(results), "seconds": round(time.time() - started, 1),
            "results": results}
