"""Run: python -m pytest -q   (no Ollama or internet needed — Ollama is faked)."""
import json
import hashlib

import pytest

from lantern import models, rag
from lantern.kiwix_source import KiwixLibrary, html_to_text
from lantern.manuals import ManualIndex, chunk
from lantern.app import create_app


class FakeOllama:
    """Deterministic stand-in: bag-of-words embeddings, canned streamed answer."""
    def __init__(self, installed=("qwen3:4b", "qwen3:14b", "nomic-embed-text:latest")):
        self.installed = list(installed)
        self.last_messages = None

    def is_up(self): return True
    def models(self): return self.installed

    def embed(self, model, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[int(hashlib.md5(w.strip(".,").encode()).hexdigest(), 16) % 64] += 1
            out.append(v)
        return out

    def chat_stream(self, model, messages):
        self.last_messages = messages
        yield from ["Boil it ", "for 1 minute [1]."]


@pytest.fixture
def zim_dir(tmp_path):
    from libzim.writer import Creator, Item, StringProvider, Hint

    class Page(Item):
        def __init__(self, path, title, body):
            super().__init__()
            self.p, self.t, self.b = path, title, body
        def get_path(self): return self.p
        def get_title(self): return self.t
        def get_mimetype(self): return "text/html"
        def get_contentprovider(self): return StringProvider(self.b)
        def get_hints(self): return {Hint.FRONT_ARTICLE: True}

    d = tmp_path / "zim"; d.mkdir()
    filler = " Additional context about safe handling and storage." * 10
    with Creator(str(d / "testbook.zim")).config_indexing(True, "eng") as c:
        c.set_mainpath("water")
        c.add_metadata("Title", "Test Survival Book")
        c.add_item(Page("water", "Water purification",
            "<html><body><script>bad()</script><h1>Water purification</h1>"
            "<p>Bring water to a rolling boil for one minute to kill pathogens.</p>"
            f"<p>{filler}</p></body></html>"))
        c.add_item(Page("knots", "Bowline knot",
            f"<html><body><p>The bowline makes a fixed loop at the end of a rope.{filler}</p></body></html>"))
    return d


@pytest.fixture
def manuals_dir(tmp_path):
    d = tmp_path / "manuals"; d.mkdir()
    (d / "radio.md").write_text("NOAA weather radio broadcasts on 162.550 MHz. " * 5)
    (d / "fire.txt").write_text("To start a fire gather tinder kindling and fuel wood. " * 5)
    return d


def test_html_to_text_strips_scripts():
    t = html_to_text("<p>Hello</p><script>evil()</script><p>world</p>")
    assert "Hello" in t and "world" in t and "evil" not in t


def test_chunk_overlaps_and_covers():
    text = "Sentence number one. " * 200
    parts = chunk(text, size=300, overlap=50)
    assert len(parts) > 5 and all(len(p) <= 300 for p in parts)


def test_best_model_by_ram():
    installed = ["qwen3:4b", "qwen3:14b", "nomic-embed-text:latest"]
    assert models.best_model(installed, ram_gb=8) == "qwen3:4b"
    assert models.best_model(installed, ram_gb=16) == "qwen3:14b"
    assert models.best_model(installed, ram_gb=64) == "qwen3:14b"   # 27b not installed
    assert models.best_model(["llama3:8b"], ram_gb=8) == "llama3:8b"  # unknown model fallback
    assert models.best_model(["nomic-embed-text"], ram_gb=8) is None


def test_kiwix_search_finds_article(zim_dir):
    lib = KiwixLibrary(str(zim_dir))
    assert lib.summary()[0]["title"] == "Test Survival Book"
    hits = lib.search("boil water", per_book=2)
    assert hits and hits[0]["title"] == "Water purification"
    assert "rolling boil" in hits[0]["text"] and "bad()" not in hits[0]["text"]


def test_manual_index_ingest_and_search(tmp_path, manuals_dir):
    idx = ManualIndex(str(tmp_path / "idx.sqlite"), FakeOllama(), "nomic-embed-text")
    res = idx.ingest_dir(str(manuals_dir))
    assert res["indexed"] == 2
    assert idx.ingest_dir(str(manuals_dir))["unchanged"] == 2      # incremental
    top = idx.search("what frequency is NOAA weather radio", k=1)[0]
    assert top["title"] == "Radio"
    assert top["book"] == "radio.md"
    (manuals_dir / "fire.txt").unlink()
    idx.ingest_dir(str(manuals_dir))
    assert [f["file"] for f in idx.files()] == ["radio.md"]          # deleted files drop out


def test_prompt_contains_numbered_sources():
    msgs = rag.build_messages("q?", [{"book": "b", "title": "t", "text": "body"}], [])
    assert msgs[0]["role"] == "system" and "[1] b — t" in msgs[-1]["content"]


def _sse(resp):
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n")[0].removeprefix("event: ")
        data = json.loads(block.split("\n")[1].removeprefix("data: "))
        events.append((kind, data))
    return events


def test_end_to_end_api(tmp_path, zim_dir, manuals_dir, monkeypatch):
    monkeypatch.setattr(models, "system_ram_gb", lambda: 16.0)
    monkeypatch.setattr("lantern.config.save", lambda u: None)
    ollama = FakeOllama()
    cfg = {"ollama_url": "x", "chat_model": "", "embed_model": "nomic-embed-text",
           "zim_dir": str(zim_dir), "manuals_dir": str(manuals_dir),
           "index_path": str(tmp_path / "i.sqlite"), "kiwix_results_per_book": 2,
           "manual_results": 2, "max_chars_per_source": 1500}
    manuals = ManualIndex(cfg["index_path"], ollama, cfg["embed_model"])
    manuals.ingest_dir(str(manuals_dir))
    client = create_app(cfg, ollama=ollama, kiwix=KiwixLibrary(str(zim_dir)), manuals=manuals).test_client()

    st = client.get("/api/status").get_json()
    assert st["model"] == "qwen3:14b" and st["books"] and len(st["manuals"]) == 2
    assert "nomic-embed-text:latest" not in st["models"]

    events = _sse(client.post("/api/ask", json={"question": "how long to boil water"}))
    kinds = [k for k, _ in events]
    assert kinds[-1] == "done" and "token" in kinds
    sources = dict(events)["sources"]
    assert any(s["title"] == "Water purification" for s in sources)
    assert "rolling boil" in ollama.last_messages[-1]["content"]

    page = client.get("/read/kiwix/testbook/water")
    assert page.status_code == 200 and b"rolling boil" in page.data
    assert client.get("/read/manual/radio.md").status_code == 200
    assert client.get("/read/manual/../secret").status_code == 404
    assert client.get("/").status_code == 200


def test_no_model_installed_reports_error(tmp_path, zim_dir, manuals_dir):
    ollama = FakeOllama(installed=["nomic-embed-text"])
    cfg = {"ollama_url": "x", "chat_model": "", "embed_model": "nomic-embed-text",
           "zim_dir": str(zim_dir), "manuals_dir": str(manuals_dir),
           "index_path": str(tmp_path / "i.sqlite"), "kiwix_results_per_book": 1,
           "manual_results": 1, "max_chars_per_source": 500}
    client = create_app(cfg, ollama=ollama, kiwix=KiwixLibrary(str(zim_dir)),
                        manuals=ManualIndex(cfg["index_path"], ollama, "e")).test_client()
    events = _sse(client.post("/api/ask", json={"question": "hi", "use_library": False}))
    assert ("error" in [k for k, _ in events])


def test_query_variants_handle_natural_questions():
    from lantern.kiwix_source import query_variants
    v = query_variants("How long do I need to boil water?")
    assert v[0] == "boil water" and "water" in v and "boil" in v
    assert query_variants("how?") == ["how?"]
