"""Library check: prove the AI can actually reach every manual and every library."""
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse


def _reachable(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Can a connection be made to this address and port? (Used to prove a port is closed.)"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


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
                    "detail": "Running" if up else "Not running. Quit Beacon and open it again."})
    has_embed = any(m.split(":")[0] == embed_model for m in installed)
    results.append({"kind": "brain", "name": f"Search model ({embed_model})", "ok": has_embed,
                    "detail": "Installed" if has_embed else "Missing, so manuals can't be searched"})
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
                        "detail": "No AI model installed"})

    # 2. Every manual: indexed, has real text, and is findable by search.
    pending = manuals.pending(manuals_dir)
    for rel in pending:
        results.append({"kind": "manual", "name": rel, "ok": False,
                        "detail": "Not indexed yet. Click Index new files."})
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
        n = f.get("chunks", 0)
        detail = f"{n} passage{'' if n == 1 else 's'}, findable" if found else "Indexed but search didn't find it"
        if f.get("scanned"):
            detail += ". Mostly scanned images, so only part of the text is readable"
        results.append({"kind": "manual", "name": rel, "ok": found, "warn": f.get("scanned"),
                        "detail": detail})
    for rel, f in info.items():  # indexed files that produced no passages at all
        if f["chunks"] == 0:
            results.append({"kind": "manual", "name": rel, "ok": False,
                            "detail": "No readable text: it's a scanned PDF, which needs text recognition (OCR) before it can be searched."})

    # 3. Every Kiwix library: opens, and a random article is findable.
    for book in kiwix.summary():
        tried, ok, title = [], False, None
        for _ in range(3):  # a few random articles: a tiny page or a cover page alone shouldn't fail the check
            title = kiwix.random_title(book["id"])
            if not title or title in tried:
                continue
            tried.append(title)
            if kiwix.search(title, per_book=5, max_chars=200, only=book["id"]):
                ok = True
                break
        if not tried:
            results.append({"kind": "library", "name": book["title"], "ok": False,
                            "detail": "Couldn't read articles from this file"})
            continue
        results.append({"kind": "library", "name": book["title"], "ok": ok,
                        "detail": f"{book['articles']:,} articles; found “{title[:40]}”" if ok
                        else "Search returned nothing for " + ", ".join(f"“{t[:40]}”" for t in tried)})

    passed = sum(r["ok"] for r in results)
    return {"passed": passed, "total": len(results), "seconds": round(time.time() - started, 1),
            "results": results}


def security(cfg: dict, drive: dict, integrity=None, sharing: dict | None = None, problems: int | None = None,
             lan_ip: str | None = None) -> list[dict]:
    """Beacon's own security self-test, shown in the health check. With the Mac's network address,
    it also knocks on the AI engine's and Beacon's ports from the network side: they must refuse."""
    out = []
    url = urlparse(cfg.get("ollama_url", ""))
    engine, engine_port = url.hostname or "", url.port or 11434
    loopback = ("127.0.0.1", "localhost", "::1")
    for name, host, port, fine in (("AI engine is private", engine, engine_port, "Only this computer can reach it"),
                                   ("Beacon itself is private", cfg.get("host"), cfg.get("port"),
                                    "Only this computer, unless you turn on Wi-Fi sharing")):
        exposed = bool(lan_ip and port and _reachable(lan_ip, int(port)))
        if exposed:
            detail = f"Other devices can reach it at {lan_ip}:{port}. Quit Beacon and any other AI app, then open Beacon again"
        elif host not in loopback:
            detail = f"Set to listen on {host}: other devices may reach it"
        else:
            detail = fine + (f". Tested: {lan_ip}:{port} refuses connections" if lan_ip else "")
        out.append({"kind": "security", "name": name, "ok": host in loopback and not exposed, "detail": detail})
    if sharing is not None:
        on = sharing.get("on")
        out.append({"kind": "security", "name": "Wi-Fi sharing", "ok": True, "warn": bool(on),
                    "detail": (f"On: {sharing.get('guests', 0)} device(s) signed in with the code" if on else "Off")})
    if problems is not None:
        out.append({"kind": "security", "name": "Sign-in problems in the last day", "ok": True, "warn": problems > 0,
                    "detail": f"{problems} blocked or failed attempt(s). Details are in Share, under Connections" if problems
                    else "None: no wrong codes or blocked requests"})
    if drive.get("encrypted") is not None:
        enc = drive["encrypted"]
        out.append({"kind": "security", "name": "Drive encryption", "ok": True, "warn": not enc,
                    "detail": "Encrypted: locked with a password when unplugged" if enc else
                    "Not encrypted: anyone who finds the drive can read it. See START-HERE.txt to lock it"})
    if integrity is not None and integrity.map:
        res = integrity.verify()
        bad = [r["file"] for r in res if not r["ok"]]
        skipped = sum(1 for r in res if r.get("skipped"))
        if bad:
            out.append({"kind": "security", "name": "Downloaded files unchanged", "ok": False,
                        "detail": "Changed since download: " + ", ".join(Path(b).name for b in bad[:5])
                        + (f" and {len(bad) - 5} more" if len(bad) > 5 else "") + ". Download them again."})
        else:
            out.append({"kind": "security", "name": "Downloaded files unchanged", "ok": True,
                        "detail": f"{len(res) - skipped} match their download fingerprints"
                        + (f"; {skipped} large file(s) were verified when downloaded" if skipped else "")})
    return out
