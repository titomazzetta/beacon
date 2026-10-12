"""Run: python -m pytest -q   (no AI engine, no internet: both are faked)."""
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from beacon import checks, library, mapdata, models, plans, rag, system
from beacon.app import create_app, mini_md
from beacon.kiwix_source import KiwixLibrary, html_to_text, query_variants
from beacon.manuals import ManualIndex, chunk
from beacon.places import Places, bearing_deg, compass_point, haversine_km, parse_coords, route_summary

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ fakes

class FakeOllama:
    """Bag-of-words embeddings, canned streamed answers."""
    def __init__(self, installed=("qwen3:4b", "qwen3:14b", "nomic-embed-text:latest")):
        self.installed = list(installed)
        self.last_messages, self.last_options = None, None

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

    def chat_stream(self, model, messages, options=None):
        self.last_messages, self.last_options = messages, options
        yield from ["Boil it ", "for 1 minute [1]."]

    def generate_once(self, model, prompt): return "READY"

    def pull(self, model):
        yield {"status": "pulling", "total": 100, "completed": 50}
        yield {"status": "success"}

    def unload(self, model): self.unloaded = model


class FakeResp:
    def __init__(self, body=b"", status=200, headers=None, text=None):
        self.body, self.status_code = body, status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.text = text if text is not None else body.decode("utf-8", "ignore")
        self.content = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self):
        if self.status_code >= 400:
            raise library.requests.HTTPError(str(self.status_code))
    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]
    def json(self): return json.loads(self.text)


class FakeHTTP:
    """Routes URL → response. Honors Range for downloads."""
    RequestException = library.requests.RequestException

    def __init__(self, routes=None, online=True):
        self.routes, self.online, self.calls = routes or {}, online, []

    def head(self, url, **kw):
        if not self.online:
            raise library.requests.ConnectionError("offline")
        return FakeResp(status=200)

    def get(self, url, headers=None, params=None, **kw):
        self.calls.append((url, params, headers))
        if not self.online:
            raise library.requests.ConnectionError("offline")
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        for k, v in self.routes.items():
            if key.startswith(k) or url == k:
                if isinstance(v, bytes) and headers and "Range" in headers:
                    start = int(headers["Range"].split("=")[1].rstrip("-"))
                    return FakeResp(v[start:], status=206)
                return FakeResp(v) if isinstance(v, bytes) else FakeResp(text=v, body=v.encode())
        return FakeResp(status=404)


OPDS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/">
  <entry><title>WikiMed</title><name>mdwiki_en_all</name><flavour>maxi</flavour><updated>2026-05-01T00:00:00Z</updated>
    <language>eng</language><articleCount>70000</articleCount>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="2000" href="https://download.kiwix.org/zim/other/mdwiki_en_all_maxi_2026-05.zim.meta4"/></entry>
  <entry><title>WikiMed</title><name>mdwiki_en_all</name><flavour>nopic</flavour><updated>2026-05-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="900" href="https://download.kiwix.org/zim/other/mdwiki_en_all_nopic_2026-05.zim.meta4"/></entry>
  <entry><title>WikiMed (old)</title><name>mdwiki_en_all</name><flavour>maxi</flavour><updated>2025-01-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="1900" href="https://download.kiwix.org/zim/other/mdwiki_en_all_maxi_2025-01.zim.meta4"/></entry>
</feed>"""


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def zim_dir(tmp_path):
    from libzim.writer import Creator, Hint, Item, StringProvider

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
                        f"<p>Bring water to a rolling boil for one minute to kill pathogens.</p><p>{filler}</p></body></html>"))
        c.add_item(Page("knots", "Bowline knot",
                        f"<html><body><p>The bowline makes a fixed loop at the end of a rope.{filler}</p></body></html>"))
    return d


@pytest.fixture
def env(tmp_path, zim_dir):
    """A complete data folder with cards, a ZIM, places and a book."""
    root = tmp_path / "drive"
    man = root / "library" / "manuals"
    (man / "cards").mkdir(parents=True)
    (man / "radio.md").write_text("# Radio Card\n" + "NOAA weather radio broadcasts on 162.550 MHz. " * 5)
    (man / "fire.txt").write_text("To start a fire gather tinder kindling and fuel wood. " * 5)
    (man / "cards" / "first-aid-essentials.md").write_text("# Emergency First Aid Card\n\n1. Press hard on the wound.\n")
    (man / "cards" / "BEACON-CLIFFNOTES.txt").write_text("CLIFF NOTES\nBoil water 1 minute.\n")
    books = root / "library" / "books" / "reading"; books.mkdir(parents=True)
    (books / "Test-Book.txt").write_text("License junk\n*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
                                         "Chapter one <b>bold?</b>\n\nSecond paragraph.\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\nmore junk")
    maps = root / "maps"; maps.mkdir(parents=True)
    (maps / "places.tsv").write_text(
        "Atlanta\tAtlanta\t33.749\t-84.38798\tUS\tGeorgia\tUnited States\t498715\n"
        "Denver\tDenver\t39.73915\t-104.9847\tUS\tColorado\tUnited States\t715522\n"
        "Athens\tAthens\t33.96095\t-83.37794\tUS\tGeorgia\tUnited States\t127315\n"
        "Athens\tAthens\t37.98376\t23.72784\tGR\tAttica\tGreece\t664046\n"
        "Toronto\tToronto\t43.70011\t-79.4163\tCA\tOntario\tCanada\t2600000\n"
        "São Paulo\tSao Paulo\t-23.5475\t-46.63611\tBR\tSão Paulo\tBrazil\t10021295\n")
    (maps / "world.pmtiles").write_bytes(bytes(range(256)) * 40)
    cfg = {"ollama_url": "http://127.0.0.1:11435", "chat_model": "", "embed_model": "nomic-embed-text",
           "zim_dir": str(zim_dir), "manuals_dir": str(man), "books_dir": str(root / "library" / "books"),
           "index_path": str(root / "data" / "idx.sqlite"), "data_root": str(root), "host": "127.0.0.1", "port": 1,
           "mesh_watch": False}
    ollama = FakeOllama()
    manuals = ManualIndex(cfg["index_path"], ollama, cfg["embed_model"], cfg["manuals_dir"])
    manuals.ingest_dir(cfg["manuals_dir"], progress=lambda m: None)
    return {"cfg": cfg, "ollama": ollama, "manuals": manuals, "root": root, "zim_dir": zim_dir}


def make_client(env, http=None, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(models, "system_ram_gb", lambda: 16.0)
        monkeypatch.setattr("beacon.config.save", lambda u: None)
    app = create_app(dict(env["cfg"]), ollama=env["ollama"], kiwix=KiwixLibrary(str(env["zim_dir"])),
                     manuals=env["manuals"], http=http or FakeHTTP(online=False))
    c = app.test_client()
    c.environ_base["HTTP_X_BEACON"] = "1"          # what Beacon's own pages send with every action
    return app, c


def sse(resp):
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


# ------------------------------------------------------------------ text, search, brain

def test_html_to_text_strips_scripts():
    t = html_to_text("<p>Hello</p><script>evil()</script><p>world</p>")
    assert "Hello" in t and "world" in t and "evil" not in t


def test_chunk_overlaps_and_covers():
    parts = chunk("Sentence number one. " * 200, size=300, overlap=50)
    assert len(parts) > 5 and all(len(p) <= 300 for p in parts)


def test_query_variants_handle_natural_questions():
    v = query_variants("How long do I need to boil water?")
    assert v[0] == "boil water" and "water" in v and "boil" in v
    assert query_variants("how?") == ["how?"]


def test_brain_scales_with_memory():
    inst = ["qwen3:4b", "qwen3:14b", "nomic-embed-text:latest"]
    assert models.best_model(inst, ram_gb=8) == "qwen3:4b"
    assert models.best_model(inst, ram_gb=16) == "qwen3:14b"
    assert models.best_model(inst, ram_gb=64) == "qwen3:14b"       # bigger ones not installed
    assert models.best_model(["llama3:8b"], ram_gb=8) == "llama3:8b"
    assert models.best_model(["nomic-embed-text"], ram_gb=8) is None
    assert models.recommended(8)["model"] == "qwen3:4b"
    assert models.recommended(36)["model"] == "qwen3.6:27b"
    assert models.recommended(128)["model"] == "gpt-oss:120b"
    assert models.profile(8)["num_ctx"] < models.profile(16)["num_ctx"] < models.profile(64)["num_ctx"]


def test_kiwix_search_finds_article(zim_dir):
    lib = KiwixLibrary(str(zim_dir))
    assert lib.summary()[0]["title"] == "Test Survival Book"
    hits = lib.search("how long should I boil water", per_book=2)
    assert hits and hits[0]["title"] == "Water purification"
    assert "rolling boil" in hits[0]["text"] and "bad()" not in hits[0]["text"]
    assert lib.random_title("testbook") in ("Water purification", "Bowline knot")
    assert lib.search("bowline", only="nope") == []


def test_manual_index(tmp_path):
    d = tmp_path / "m"; (d / "sub").mkdir(parents=True)
    (d / "radio.md").write_text("# Radio\n" + "NOAA weather radio broadcasts on 162.550 MHz. " * 5)
    (d / "sub" / "fire.txt").write_text("To start a fire gather tinder kindling and fuel wood. " * 5)
    (d / "._junk.md").write_text("mac metadata")
    idx = ManualIndex(str(tmp_path / "i.sqlite"), FakeOllama(), "e", str(d))
    assert idx.pending(str(d)) == ["radio.md", "sub/fire.txt"]
    assert idx.ingest_dir(str(d), progress=lambda m: None)["indexed"] == 2
    assert idx.ingest_dir(str(d), progress=lambda m: None)["unchanged"] == 2
    assert idx.pending(str(d)) == []
    top = idx.search("what frequency is NOAA weather radio", k=1)[0]
    assert top["book"] == "Radio" and top["title"] == "" and top["ref"].startswith("radio.md")   # shown by its heading
    idx.display = {"radio.md": "NOAA Weather Radio guide"}
    assert idx.search("what frequency is NOAA weather radio", k=1)[0]["book"] == "NOAA Weather Radio guide"
    fire = idx.search("start a fire with tinder", k=1)[0]
    assert fire["ref"].startswith("sub/fire.txt")
    assert len(idx.samples()) == 2
    # a long manual can't fill every slot: at most two passages per document, and titles count
    (d / "long.md").write_text("# Water Card\n\n" + "\n\n".join(f"Boil water for one minute, step {i}. " * 40 for i in range(6)))
    idx.ingest_dir(str(d), progress=lambda m: None)
    hits = idx.search("how do I boil water", k=4)
    assert sum(h["ref"].startswith("long.md") for h in hits) == 2 and hits[0]["book"] == "Water Card"
    (d / "sub" / "fire.txt").unlink()
    idx.ingest_dir(str(d), progress=lambda m: None)
    assert [f["file"] for f in idx.files()] == ["long.md", "radio.md"]


def test_gather_respects_brain_budget(env, zim_dir):
    small = {"num_ctx": 1024, "sources": 2, "chars": 500}
    big = {"num_ctx": 32768, "sources": 12, "chars": 4000}
    k = KiwixLibrary(str(zim_dir))
    a = rag.gather("boil water", k, env["manuals"], small)
    b = rag.gather("boil water", k, env["manuals"], big)
    assert len(a) <= 2 and sum(len(s["text"]) for s in a) <= 1024 * 4
    assert len(b) >= len(a)
    assert {s["kind"] for s in b} == {"manual", "kiwix"}               # both kinds interleaved


def test_prompt_contains_numbered_sources():
    msgs = rag.build_messages("q?", [{"book": "b", "title": "t", "text": "body"}], [])
    assert msgs[0]["role"] == "system" and "[1] b — t" in msgs[-1]["content"]


# ------------------------------------------------------------------ catalog & library

def test_catalog_is_consistent():
    cat = library.load_catalog()
    ids = [i["id"] for i in library.all_items(cat)]
    assert len(ids) == len(set(ids)), "duplicate item ids"
    tiers = {t["id"] for t in cat["tiers"]}
    assert tiers == set(library.TIER_ORDER)
    for it in library.all_items(cat):
        assert it["tier"] in tiers and it["title"]
        if it["type"] == "zim":
            assert it.get("name") or it.get("query")
        elif it.get("files"):                       # several PDFs that belong together
            assert it["type"] == "pdf" and "license" in it
            assert all(f["url"].startswith("https://") and f["file"] for f in it["files"])
        elif it["type"] in ("pdf", "text", "page"):
            assert it["url"].startswith("https://") and it["file"]
            assert "license" in it
            if it["type"] == "page":
                assert it["file"].endswith(".md")
        elif it["type"] == "link":
            assert it["url"].startswith("https://")
        else:
            pytest.fail(f"unknown type {it['type']}")
        if it.get("shelf"):
            assert it["type"] == "text"
    for tier in library.TIER_ORDER:
        assert library.items_for_tier(cat, tier)


def test_tiers_are_cumulative_and_groups_exclusive():
    cat = library.load_catalog()
    sizes = [len(library.items_for_tier(cat, t)) for t in library.TIER_ORDER]
    assert sizes == sorted(sizes)
    every = library.items_for_tier(cat, "everything")
    wp = [i for i in every if i.get("group") == "wikipedia-full"]
    assert len(wp) == 1 and wp[0]["flavour"] == "nopic"                 # maxi is opt-in only
    assert not any(i["type"] == "link" for i in every)
    med = library.items_for_tier(cat, "core", ["medical"])
    assert med and all(i["band"] == "medical" for i in med)


def test_opds_parse_and_pick():
    entries = library.parse_opds(OPDS)
    assert len(entries) == 3 and entries[0]["url"].endswith(".zim") and entries[0]["size"] == 2000
    best = library._pick(entries, "mdwiki_en_all", "maxi")
    assert best["filename"] == "mdwiki_en_all_maxi_2026-05.zim"        # newest maxi
    assert library._pick(entries, "mdwiki_en_all", "nopic")["size"] == 900


def test_kiwix_catalog_resolves_and_caches(tmp_path):
    http = FakeHTTP({library.OPDS: OPDS})
    kc = library.KiwixCatalog(str(tmp_path / "c.json"), http)
    item = {"id": "wikimed", "name": "mdwiki_en_all", "flavour": "maxi", "query": "WikiMed"}
    r = kc.resolve(item)
    assert r["filename"] == "mdwiki_en_all_maxi_2026-05.zim"
    n = len(http.calls)
    assert kc.resolve(item)["size"] == 2000 and len(http.calls) == n   # cached
    assert library.KiwixCatalog(str(tmp_path / "c.json"), http).cache["wikimed"]


def test_downloader_resumes_and_records(tmp_path):
    body = b"x" * 5000
    http = FakeHTTP({"https://example.org/file.pdf": body})
    inst = library.Installed(str(tmp_path / "installed.json"))
    done = []
    dl = library.Downloader(inst, on_done=done.append, http=http)
    dest = tmp_path / "out" / "file.pdf"
    dest.parent.mkdir()
    (dest.parent / "file.pdf.part").write_bytes(body[:1200])          # interrupted earlier
    dl.add({"id": "f", "title": "F", "type": "pdf"}, "https://example.org/file.pdf", dest)
    dl.worker.join(5)
    assert dest.read_bytes() == body
    assert http.calls[-1][2]["Range"] == "bytes=1200-"
    assert inst.file_for("f") == str(dest) and done and done[0]["state"] == "done"


def test_downloader_reports_failures_and_tasks(tmp_path):
    inst = library.Installed(str(tmp_path / "i.json"))
    dl = library.Downloader(inst, http=FakeHTTP({}))
    dl.add({"id": "missing", "title": "M", "type": "pdf"}, "https://example.org/nope.pdf", tmp_path / "n.pdf")
    dl.worker.join(5)
    assert dl.jobs["missing"]["state"] == "failed"

    def task(job):
        job["detail"] = "working"; job["total"], job["done"] = 10, 10
    dl.add_task("t1", "Task", task)
    dl.worker.join(5)
    assert dl.jobs["t1"]["state"] == "done"
    assert all("fn" not in j for j in dl.status())


# ------------------------------------------------------------------ places & maps

def test_parse_coords_formats():
    assert parse_coords("33.75, -84.39") == (33.75, -84.39)
    assert parse_coords("33.75N 84.39W") == (33.75, -84.39)
    lat, lon = parse_coords("33°45'N 84°23'W")
    assert abs(lat - 33.75) < 0.01 and abs(lon + 84.383) < 0.01
    assert parse_coords("Atlanta") is None
    assert parse_coords("95, 10") is None


def test_navigation_math():
    assert abs(haversine_km(33.749, -84.388, 43.700, -79.416) - 1187) < 15   # Atlanta → Toronto
    assert compass_point(0) == "N" and compass_point(95) == "E" and compass_point(225) == "SW"
    assert 10 < bearing_deg(33.749, -84.388, 43.700, -79.416) < 30
    near = route_summary({"lat": 33.749, "lon": -84.388}, {"lat": 33.96, "lon": -83.378})
    far = route_summary({"lat": 33.749, "lon": -84.388}, {"lat": 41.9, "lon": 12.5})
    assert "walk_days" in near and "walk_days" not in far and far["flight_hours"] > 8


def test_places_search_and_nearest(env):
    p = Places(str(env["root"] / "maps" / "places.tsv"))
    assert p.search("athens")[0]["label"].endswith("Greece")          # bigger city first
    assert p.search("athens, georgia")[0]["label"] == "Athens, Georgia, United States"
    assert p.search("sao paulo")[0]["label"].startswith("São Paulo")  # accents folded
    assert p.search("33.75, -84.39")[0]["exact"]
    assert p.nearest(33.8, -84.4, 1)[0]["name"].startswith("Atlanta")
    assert Places("/nope.tsv").available is False


def test_geonames_conversion_and_map_helpers():
    cities = "\t".join(["1", "Atlanta", "Atlanta", "", "33.749", "-84.38798", "P", "PPLA", "US", "", "GA",
                        "", "", "", "498715", "", "", "", ""])
    lines = mapdata.convert_geonames(cities, "#hdr\nUS\tUSA\t840\tUS\tUnited States\n", "US.GA\tGeorgia\tGeorgia\t1\n")
    assert lines == ["Atlanta\tAtlanta\t33.749\t-84.38798\tUS\tGeorgia\tUnited States\t498715"]
    bb = [float(x) for x in mapdata.bbox_around(33.75, -84.39, 300).split(",")]
    assert bb[0] < -84.39 < bb[2] and bb[1] < 33.75 < bb[3]
    assert mapdata.safe_name("Monte Carlo, Monaco!") == "monte-carlo-monaco"


def test_build_places_with_fake_downloads(tmp_path):
    row = "\t".join(["1", "Toronto", "Toronto", "", "43.7", "-79.4", "P", "PPLA", "CA", "", "08",
                     "", "", "", "2600000", "", "", "", ""])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cities5000.txt", row + "\n")
    http = FakeHTTP({mapdata.GEONAMES + "cities5000.zip": buf.getvalue(),
                     mapdata.GEONAMES + "countryInfo.txt": "CA\tCAN\t124\tCA\tCanada\n",
                     mapdata.GEONAMES + "admin1CodesASCII.txt": "CA.08\tOntario\tOntario\t1\n"})
    job = {}
    out = mapdata.build_places(str(tmp_path), job, http)
    assert out.read_text().startswith("Toronto\tToronto\t43.7\t-79.4\tCA\tOntario\tCanada")
    assert Places(str(out)).search("toronto")


def test_map_tool_is_pinned_and_checked_before_it_runs(tmp_path, monkeypatch):
    import os
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pmtiles", "#!/bin/sh\necho ok\n")
    fake = buf.getvalue()
    monkeypatch.setattr(mapdata, "_asset_pattern", lambda: "Darwin_arm64")
    name, pinned = mapdata.PMTILES_FILES["Darwin_arm64"]
    assert len(pinned) == 64 and all(len(h) == 64 for _, h in mapdata.PMTILES_FILES.values())
    url = f"https://github.com/protomaps/go-pmtiles/releases/download/v{mapdata.PMTILES_VERSION}/{name}"
    with pytest.raises(RuntimeError, match="checksum"):
        mapdata.pmtiles_cli(str(tmp_path / "a"), FakeHTTP({url: fake}))              # not the published bytes
    assert not (tmp_path / "a" / "tools" / "pmtiles").exists()
    monkeypatch.setitem(mapdata.PMTILES_FILES, "Darwin_arm64", (name, hashlib.sha256(fake).hexdigest()))
    exe = mapdata.pmtiles_cli(str(tmp_path / "b"), FakeHTTP({url: fake}))
    assert exe.read_text().startswith("#!/bin/sh") and os.access(exe, os.X_OK)


# ------------------------------------------------------------------ plans, system, checks

def test_plan_build_includes_details():
    tpl = plans.get("leave-country")
    q, instr = plans.build(tpl, {"location": "Denver", "destination": "Canada", "documents": "US passport, Canadian work permit",
                                 "phase": "It's happening now"}, "Denver at 39.7, -105.0")
    assert "Next 15 minutes" in instr and "What to get" not in instr
    assert "Leaving the country" in instr and "Canadian work permit" in instr and "Denver at 39.7" in instr
    assert "passport" in q
    assert len(plans.public_list()) == len(plans.TEMPLATES) >= 12
    assert all(t["sections"] for t in plans.TEMPLATES)


def test_system_check_recommends(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "system_ram_gb", lambda: 16.0)
    rep = system.check(str(tmp_path), ["qwen3:4b"])
    assert rep["recommended"]["model"] == "qwen3:14b" and rep["active_model"] == "qwen3:4b"
    assert any("stronger brain" in n for n in rep["notes"])
    assert next(t for t in rep["tiers"] if t["model"] == "qwen3:4b")["installed"]
    none = system.check(str(tmp_path), [])
    assert any("No AI model" in n for n in none["notes"])


def test_library_check_finds_everything(env, zim_dir):
    rep = checks.run(env["manuals"], KiwixLibrary(str(zim_dir)), env["ollama"], "qwen3:4b",
                     "nomic-embed-text", env["cfg"]["manuals_dir"])
    assert rep["passed"] == rep["total"], [r for r in rep["results"] if not r["ok"]]
    kinds = {r["kind"] for r in rep["results"]}
    assert kinds == {"brain", "manual", "library"}
    (Path(env["cfg"]["manuals_dir"]) / "new.md").write_text("# New\nsomething new " * 5)
    rep2 = checks.run(env["manuals"], KiwixLibrary(str(zim_dir)), env["ollama"], "qwen3:4b",
                      "nomic-embed-text", env["cfg"]["manuals_dir"])
    assert any(r["name"] == "new.md" and not r["ok"] for r in rep2["results"])


def test_mini_md_for_binder():
    out = mini_md("# Title\n\nText with **bold** & <tags>.\n\n- a\n- b\n\n1. one\n2. two\n\n| x | y |\n|---|---|\n| 1 | 2 |")
    assert "<h1>Title</h1>" in out and "<b>bold</b>" in out and "&lt;tags&gt;" in out
    assert "<ul><li>a</li><li>b</li></ul>" in out and "<ol><li>one</li>" in out and "<td>1</td>" in out


# ------------------------------------------------------------------ the web app

def test_ask_and_status(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    st = c.get("/api/status").get_json()
    assert st["model"] == "qwen3:14b" and st["books"] and len(st["manuals"]) == 4
    ev = sse(c.post("/api/ask", json={"question": "how long to boil water"}))
    kinds = [k for k, _ in ev]
    assert kinds[-1] == "done" and "token" in kinds
    assert any(s["title"] == "Water purification" for s in dict(ev)["sources"])
    assert "rolling boil" in env["ollama"].last_messages[-1]["content"]
    assert env["ollama"].last_options["num_ctx"] == models.profile(16)["num_ctx"]
    assert c.post("/api/ask", json={"question": " "}).status_code == 400


def test_no_model_installed_reports_error(env):
    env["ollama"].installed = ["nomic-embed-text"]
    _, c = make_client(env)
    ev = sse(c.post("/api/ask", json={"question": "hi", "use_library": False}))
    assert "error" in [k for k, _ in ev]


def test_plan_uses_household_profile_and_places(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    assert c.post("/api/profile", json={"home": "Denver", "medical": "Dad: insulin", "bogus": "x"}).get_json()["saved"]
    prof = c.get("/api/profile").get_json()
    assert prof == {"home": "Denver", "medical": "Dad: insulin"}
    ev = sse(c.post("/api/plan", json={"template": "evacuate", "answers": {"destination": "Toronto"}}))
    assert ev[-1][0] == "done"
    prompt = env["ollama"].last_messages[-1]["content"]
    assert "Dad: insulin" in prompt and "Toronto, Ontario, Canada" in prompt and "km" in prompt
    assert c.post("/api/plan", json={"template": "nope"}).status_code == 404


def test_system_and_check_endpoints(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    s = c.get("/api/system").get_json()
    assert s["engine_up"] and s["active_model"] == "qwen3:14b" and s["profile"]["name"] == "Standard"
    c.post("/api/check", json={})
    import time
    for _ in range(50):
        r = c.get("/api/check").get_json()
        if r["report"] and not r["running"]:
            break
        time.sleep(0.1)
    assert r["report"]["passed"] == r["report"]["total"]


def test_places_route_and_map_files(env):
    _, c = make_client(env)
    assert c.get("/api/places?q=toronto").get_json()["results"][0]["label"].startswith("Toronto")
    near = c.get("/api/places/nearest?lat=33.7&lon=-84.4").get_json()
    assert near[0]["name"].startswith("Atlanta")
    r = c.post("/api/route", json={"from": {"lat": 33.749, "lon": -84.388}, "to": {"lat": 43.7, "lon": -79.4}}).get_json()
    assert r["compass"] in ("NNE", "N", "NE")
    maps = c.get("/api/maps").get_json()
    assert maps["places"] and maps["maps"][0]["file"] == "world.pmtiles"
    part = c.get("/maps/world.pmtiles", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and len(part.data) == 10                 # Range works (pmtiles needs it)
    assert c.get("/maps/../data/idx.sqlite").status_code == 404
    assert c.get("/maps/%2e%2e/data/idx.sqlite").status_code == 404


def test_library_endpoints_offline_and_online(env, monkeypatch, tmp_path):
    _, c = make_client(env)
    lib = c.get("/api/library").get_json()
    assert lib["online"] is False and len(lib["bands"]) >= 12 and lib["buy_list"]["books"]
    assert c.post("/api/library/sizes", json={}).get_json() == {"online": False}
    # online: a PDF item downloads and lands in the right band folder
    cat = library.load_catalog()
    item = next(i for i in library.all_items(cat) if i["id"] == "fema-ready")
    http = FakeHTTP({item["url"]: b"%PDF-1.4 fake", library.OPDS: OPDS})
    app, c2 = make_client(env, http=http)
    r = c2.post("/api/library/download", json={"ids": ["fema-ready"]}).get_json()
    assert r["queued"] == 1 and not r["errors"]
    app.config["downloader"].worker.join(5)
    dest = Path(env["cfg"]["manuals_dir"]) / "civil-defense" / item["file"]
    assert dest.read_bytes().startswith(b"%PDF")
    lib2 = c2.get("/api/library").get_json()
    st = next(i for b in lib2["bands"] for i in b["items"] if i["id"] == "fema-ready")
    assert st["installed"]


def test_books_cards_binder_and_readers(env):
    _, c = make_client(env)
    books = c.get("/api/books").get_json()
    assert books[0]["path"] == "reading/Test-Book.txt"
    page = c.get("/read/book/reading/Test-Book.txt").get_data(as_text=True)
    assert "Chapter one &lt;b&gt;bold?&lt;/b&gt;" in page and "License junk" not in page and "more junk" not in page
    assert c.get("/read/book/../../data/idx.sqlite").status_code == 404
    cards = c.get("/api/cards").get_json()
    assert {x["title"] for x in cards} >= {"Emergency First Aid Card"}
    r = c.get("/read/manual/cards/first-aid-essentials.md")
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("text/plain")
    assert c.get("/read/manual/../secret").status_code == 404
    c.post("/api/profile", json={"home": "<script>x</script>"})
    binder = c.get("/binder").get_data(as_text=True)
    assert "CLIFF NOTES" in binder and "Emergency First Aid Card" in binder
    assert "<script>x</script>" not in binder and "&lt;script&gt;" in binder
    assert c.get("/").status_code == 200
    assert c.get("/static/vendor/maplibre-gl.mjs").headers["Content-Type"].startswith("text/javascript")


def test_model_pull_queues_task(env):
    app, c = make_client(env)
    assert c.post("/api/models/pull", json={"model": "qwen3:8b"}).get_json()["queued"]
    app.config["downloader"].worker.join(5)
    job = app.config["downloader"].jobs["model-qwen3:8b"]
    assert job["state"] == "done" and job["detail"] == "success"


def test_drive_moves_between_computers_without_reindexing(tmp_path):
    """The same USB mounts as /Volumes/BEACON on a Mac and E:\\ on Windows."""
    import shutil
    a = tmp_path / "mac" / "Beacon"
    man = a / "library" / "manuals"; man.mkdir(parents=True)
    (man / "radio.md").write_text("# Radio\n" + "NOAA weather radio broadcasts on 162.550 MHz. " * 5)
    idx = ManualIndex(str(a / "data" / "i.sqlite"), FakeOllama(), "e", str(man))
    idx.ingest_dir(str(man), progress=lambda m: None)
    inst = library.Installed(str(a / "data" / "installed.json"), str(a))
    inst.set("fema", str(man / "radio.md"))
    b = tmp_path / "pc" / "Beacon"
    shutil.copytree(a, b, copy_function=shutil.copy2)              # keeps timestamps, like the same drive
    idx2 = ManualIndex(str(b / "data" / "i.sqlite"), FakeOllama(), "e", str(b / "library" / "manuals"))
    assert idx2.pending(str(b / "library" / "manuals")) == []
    assert idx2.ingest_dir(str(b / "library" / "manuals"), progress=lambda m: None)["unchanged"] == 1
    assert idx2.search("NOAA radio", k=1)[0]["book"] == "Radio"
    inst2 = library.Installed(str(b / "data" / "installed.json"), str(b))
    assert inst2.file_for("fema") == str(b / "library" / "manuals" / "radio.md")


def test_zim_download_resolves_in_background(env, tmp_path):
    zim_bytes = (env["zim_dir"] / "testbook.zim").read_bytes()
    url = "https://download.kiwix.org/zim/other/mdwiki_en_all_maxi_2026-05.zim"
    http = FakeHTTP({library.OPDS: OPDS, url: zim_bytes})
    new_zims = tmp_path / "zims"; new_zims.mkdir()
    env["cfg"]["zim_dir"] = str(new_zims)
    app, c = make_client(env, http=http)
    t0 = __import__("time").time()
    r = c.post("/api/library/download", json={"ids": ["wikimed"]}).get_json()
    assert r["queued"] == 1 and __import__("time").time() - t0 < 2     # returns right away
    app.config["downloader"].worker.join(10)
    job = app.config["downloader"].jobs["wikimed"]
    assert job["state"] == "done", job
    assert (new_zims / "mdwiki_en_all_maxi_2026-05.zim").exists()
    st = c.get("/api/status").get_json()
    assert any(b["title"] == "Test Survival Book" for b in st["books"])  # library reloaded live


def test_damaged_pdf_is_skipped_not_fatal(tmp_path):
    d = tmp_path / "m"; d.mkdir()
    (d / "broken.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    (d / "good.md").write_text("# Good\n" + "useful words here " * 10)
    idx = ManualIndex(str(tmp_path / "i.sqlite"), FakeOllama(), "e", str(d))
    log = []
    res = idx.ingest_dir(str(d), progress=log.append)
    assert res["indexed"] >= 1 and [f["file"] for f in idx.files()][-1] == "good.md"


# ------------------------------------------------------------------ Wi-Fi sharing, guests, quitting

GUEST = {"REMOTE_ADDR": "192.168.1.50"}


def sharing(app, code="4821"):
    """Pretend the Wi-Fi server is running without binding a real socket."""
    share = app.config["share"]
    share.server, share.code = object(), code
    return share


def test_guests_need_the_code_and_cant_change_things(env, monkeypatch):
    app, c = make_client(env, monkeypatch=monkeypatch)
    c.post("/api/profile", json={"home": "Denver", "medical": "Dad: insulin"})       # the host fills it in
    r = c.get("/", environ_base=GUEST)
    assert r.status_code == 401 and "isn't shared right now" in r.get_data(as_text=True)  # sharing is off
    sharing(app)
    assert "4-digit code" in c.get("/", environ_base=GUEST).get_data(as_text=True)
    assert c.get("/api/status", environ_base=GUEST).status_code == 401
    bad = c.get("/?code=0000", environ_base=GUEST)
    assert bad.status_code == 401 and "match. Check the Beacon screen" in bad.get_data(as_text=True)
    ok = c.get("/?code=4821", environ_base=GUEST)
    cookie = ok.headers["Set-Cookie"]
    assert ok.status_code == 302 and cookie.startswith("beacon_guest=") and "4821" not in cookie   # a token, not the code
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert c.get("/", environ_base=GUEST).status_code == 200                            # the cookie is remembered
    assert c.get("/api/system", environ_base=GUEST).get_json()["guest"] is True
    assert c.get("/api/system").get_json()["guest"] is False                            # the Mac itself
    for path in ("/api/quit", "/api/profile", "/api/share", "/api/power", "/api/library/download", "/api/models/pull", "/api/ingest"):
        assert c.post(path, json={}, environ_base=GUEST).status_code == 403, path
    assert c.get("/api/profile", environ_base=GUEST).status_code == 403
    assert "Dad: insulin" not in c.get("/binder", environ_base=GUEST).get_data(as_text=True)
    assert "Dad: insulin" in c.get("/binder").get_data(as_text=True)
    ev = sse(c.post("/api/plan", json={"template": "evacuate", "answers": {}}, environ_base=GUEST))
    assert ev[-1][0] == "done" and "Dad: insulin" not in env["ollama"].last_messages[-1]["content"]
    ev = sse(c.post("/api/ask", json={"question": "how long to boil water"}, environ_base=GUEST))
    assert "token" in [k for k, _ in ev]                                                # guests can ask
    assert c.get("/download/cards.zip", environ_base=GUEST).status_code == 200          # and save files
    app.config["share"].server = None                                                   # sharing stopped
    assert c.get("/api/status", environ_base=GUEST).status_code == 401


def test_quit_stops_the_ai_engine_and_beacon(env, monkeypatch):
    import os, subprocess, time
    app, c = make_client(env)
    engine = subprocess.Popen(["sleep", "30"])
    run = Path(env["root"]) / "data" / "run"; run.mkdir(parents=True, exist_ok=True)
    (run / "ollama.pid").write_text(str(engine.pid))
    exited = []
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(code))
    assert c.post("/api/quit", json={}).get_json() == {"stopping": True}
    for _ in range(40):
        if exited and engine.poll() is not None:
            break
        time.sleep(0.1)
    assert exited == [0] and engine.poll() is not None and not (run / "ollama.pid").exists()


def test_share_server_serves_beacon_on_the_network(env):
    import socket, urllib.request
    from beacon.share import Share
    app, _ = make_client(env)
    sh = Share(app, ports=(0,))                     # any free port
    st = sh.start()
    try:
        assert st["on"] and len(st["code"]) == 4 and st["code"].isdigit()
        assert st["join_url"].endswith("/?code=" + st["code"])
        body = urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/api/ping", timeout=5).read()
        assert json.loads(body)["ok"] is True
    finally:
        assert sh.stop() == {"on": False, "error": ""}
    blocker = socket.socket(); blocker.bind(("0.0.0.0", 0)); port = blocker.getsockname()[1]; blocker.listen()
    try:
        failed = Share(app, ports=(port,)).start()
        assert failed["on"] is False and failed["error"]
    finally:
        blocker.close()


def test_low_power_turns_the_ai_off_but_keeps_cards(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    assert c.post("/api/power", json={"low": True}).get_json() == {"low": True}
    assert c.get("/api/system").get_json()["low_power"] is True
    import time; time.sleep(0.2)
    assert env["ollama"].unloaded == "qwen3:14b"                                       # memory freed right away
    ev = sse(c.post("/api/ask", json={"question": "my friend is bleeding a lot"}))
    kinds = [k for k, _ in ev]
    assert kinds[0] == "card" and "error" in kinds and "token" not in kinds
    assert "Low power" in dict(ev)["error"]
    assert "error" in [k for k, _ in sse(c.post("/api/translate", json={"text": "water", "to": "Spanish"}))]
    c.post("/api/power", json={"low": False})
    assert "token" in [k for k, _ in sse(c.post("/api/ask", json={"question": "boil water"}))]


def test_matching_quick_card(env, monkeypatch):
    assert rag.match_card("Someone is bleeding badly from the leg") == "first-aid-essentials.md"
    assert rag.match_card("A tornado warning was just issued") == "severe-weather.md"
    assert rag.match_card("It's a heat wave and grandma is dizzy") == "severe-weather.md"
    assert rag.match_card("How do we set up a perimeter and a watch schedule?") == "defensive-perimeter.md"
    assert rag.match_card("How do I evade checkpoints and stay hidden?") == "evasion-basics.md"
    assert rag.match_card("What's the capital of France?") is None
    _, c = make_client(env, monkeypatch=monkeypatch)
    ev = sse(c.post("/api/ask", json={"question": "someone is bleeding from a deep cut"}))
    assert ev[0] == ("card", {"file": "first-aid-essentials.md", "title": "Emergency First Aid Card"})
    plan = sse(c.post("/api/plan", json={"template": "tornado", "answers": {}}))
    assert ("card", {"file": "first-aid-essentials.md", "title": "Emergency First Aid Card"}) not in plan  # no such card on this test drive


def test_translate_streams_plain_translation(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    ev = sse(c.post("/api/translate", json={"text": "We need clean water.", "to": "Spanish"}))
    assert [k for k, _ in ev][-1] == "done" and "token" in [k for k, _ in ev]
    msgs = env["ollama"].last_messages
    assert "translate" in msgs[0]["content"].lower() and msgs[-1]["content"].startswith("Translate into Spanish")
    assert c.post("/api/translate", json={"text": "", "to": "Spanish"}).status_code == 400


def make_pdf(text: str) -> bytes:
    """A tiny one-page PDF with real, extractable text."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % x for x in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_pdfs_inside_kiwix_archives_are_searchable(tmp_path):
    from libzim.writer import Creator, Hint, Item, StringProvider

    class Doc(Item):
        def __init__(self, path, title, body, mime):
            super().__init__()
            self.p, self.t, self.b, self.m = path, title, body, mime
        def get_path(self): return self.p
        def get_title(self): return self.t
        def get_mimetype(self): return self.m
        def get_contentprovider(self): return StringProvider(self.b)
        def get_hints(self): return {Hint.FRONT_ARTICLE: self.m == "text/html"}

    zims = tmp_path / "zim"; zims.mkdir()
    with Creator(str(zims / "fieldmanuals_en_2026-01.zim")).config_indexing(True, "eng") as c:
        c.set_mainpath("index")
        c.add_metadata("Title", "Field Manuals")
        c.add_item(Doc("index", "Index", "<html><body><p>List of manuals.</p></body></html>", "text/html"))
        c.add_item(Doc("files/fm-4-25.pdf", "FM 4-25.11 First Aid", make_pdf("Apply the tourniquet two inches above the wound"), "application/pdf"))
    kiwix = KiwixLibrary(str(zims))
    idx = ManualIndex(str(tmp_path / "i.sqlite"), FakeOllama(), "e", str(tmp_path / "manuals"))
    (tmp_path / "manuals").mkdir()
    res = idx.ingest_zim_pdfs(kiwix, progress=lambda m: None)
    assert res["indexed"] == 1
    f = idx.files()[0]
    assert f["path"] == "zim:fieldmanuals_en_2026-01/files/fm-4-25.pdf" and f["title"] == "FM 4-25.11 First Aid"
    hit = idx.search("tourniquet above the wound", k=1)[0]
    assert hit["kind"] == "zimpdf" and hit["book"] == "FM 4-25.11 First Aid" and hit["page"] == 1
    assert hit["ref"] == "fieldmanuals_en_2026-01/files/fm-4-25.pdf"
    assert idx.ingest_zim_pdfs(kiwix, progress=lambda m: None)["indexed"] == 0       # unchanged: skipped
    idx.ingest_dir(str(tmp_path / "manuals"), progress=lambda m: None)               # doesn't drop them
    assert idx.files()
    content, mime = kiwix.article_html("fieldmanuals_en_2026-01", "files/fm-4-25.pdf")
    assert mime == "application/pdf" and content.startswith(b"%PDF")
    idx.ingest_zim_pdfs(KiwixLibrary(str(tmp_path / "empty")), progress=lambda m: None)  # archive removed
    assert idx.files() == []


def test_multi_file_and_web_page_downloads(env):
    cat = library.load_catalog()
    multi = next(i for i in library.all_items(cat) if i.get("files"))
    page = next(i for i in library.all_items(cat) if i["type"] == "page")
    routes = {f["url"]: b"%PDF-1.4 part" for f in multi["files"]}
    routes[page["url"]] = "<html><body><h1>Shelter</h1><p>Stay inside and listen to the radio.</p><script>x()</script></body></html>"
    app, c = make_client(env, http=FakeHTTP(routes))
    r = c.post("/api/library/download", json={"ids": [multi["id"], page["id"]]}).get_json()
    assert r["queued"] == 2 and not r["errors"]
    app.config["downloader"].worker.join(10)
    jobs = app.config["downloader"].jobs
    assert jobs[multi["id"]]["state"] == "done" and jobs[page["id"]]["state"] == "done", jobs
    folder = Path(env["cfg"]["manuals_dir"]) / multi["band"] / multi["id"]
    assert sorted(p.name for p in folder.iterdir()) == sorted(f["file"] for f in multi["files"])
    saved = (Path(env["cfg"]["manuals_dir"]) / page["band"] / page["file"]).read_text()
    assert saved.startswith("# " + page["title"]) and "Source: " + page["url"] in saved
    assert "Stay inside and listen to the radio." in saved and "x()" not in saved
    items = {i["id"]: i for b in c.get("/api/library").get_json()["bands"] for i in b["items"]}
    assert items[multi["id"]]["installed"] and items[page["id"]]["installed"]


def test_files_save_to_a_phone(env):
    (Path(env["root"]) / "START-HERE.txt").write_text("Start here.")
    _, c = make_client(env)
    z = zipfile.ZipFile(io.BytesIO(c.get("/download/cards.zip").data))
    assert {"Beacon cards/first-aid-essentials.md", "Beacon cards/BEACON-CLIFFNOTES.txt", "Beacon cards/START-HERE.txt"} <= set(z.namelist())
    for url in ("/read/manual/cards/first-aid-essentials.md?download=1", "/binder?download=1",
                "/read/book/reading/Test-Book.txt?download=1"):
        r = c.get(url)
        assert r.status_code == 200 and r.headers["Content-Disposition"].startswith("attachment"), url


def test_ui_files_are_served_and_wired():
    """Every element the scripts look up by id exists in the page (or is created by the scripts)."""
    import re
    app = create_app({"ollama_url": "x", "chat_model": "", "embed_model": "e", "zim_dir": "/nonexistent",
                      "manuals_dir": "/nonexistent", "books_dir": "/nonexistent", "index_path": "/tmp/beacon-ui-test/i.sqlite",
                      "data_root": "/tmp/beacon-ui-test", "host": "127.0.0.1", "port": 1}, ollama=FakeOllama(), kiwix=None)
    c = app.test_client()
    page = c.get("/").get_data(as_text=True)
    for asset in re.findall(r'(?:src|href)="(/static/[^"]+)"', page):
        r = c.get(asset)
        assert r.status_code == 200, asset
        if asset.endswith((".js", ".mjs")):
            assert "javascript" in r.headers["Content-Type"], asset
    static = ROOT / "static"
    scripts = {p.name: p.read_text() for p in (static / "js").glob("*.js")}
    known = set(re.findall(r'\bid="([\w-]+)"', page))
    for text in scripts.values():
        known |= set(re.findall(r'\bid="([\w-]+)"', text))
        known |= set(re.findall(r'id="(\w+)-\$\{', text))  # ids built from a prefix, like pf-${...}
    for name, text in scripts.items():
        for ref in re.findall(r'\$\("([\w-]+)"\)', text):
            assert ref in known or any(ref.startswith(k + "-") for k in known), f"{name} looks up #{ref}"
        for ref in re.findall(r'\$\("([\w]+)-" \+', text):
            assert ref in known, f"{name} builds ids from {ref}-"


# ------------------------------------------------------------------ security controls

def test_only_answers_to_its_own_names(env):
    """DNS rebinding: another website pointing its own domain at this Mac gets nothing."""
    _, c = make_client(env)
    assert c.get("/api/profile", headers={"Host": "evil.example"}).status_code == 403
    assert c.get("/api/profile", headers={"Host": "evil.example:8642"}).status_code == 403
    for host in ("127.0.0.1:8642", "localhost:8642", "[::1]:8642", "beacon.local", "beacon.local:8643",
                 "Studio-MacBook.local", "192.168.1.23:8643"):
        assert c.get("/api/ping", headers={"Host": host}).status_code == 200, host


def test_actions_need_beacons_own_header(env, monkeypatch):
    """CSRF: a web page elsewhere can't make Beacon do things, even on this Mac."""
    app, c = make_client(env, monkeypatch=monkeypatch)
    plain = app.test_client()                      # like a form on another website: no X-Beacon header
    for path in ("/api/quit", "/api/profile", "/api/profile/erase", "/api/share", "/api/ingest", "/api/check"):
        assert plain.post(path, data="x", content_type="text/plain").status_code == 403, path
    assert plain.post("/api/profile", json={"home": "x"}).status_code == 403
    assert c.post("/api/profile", json={"home": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/profile", json={"home": "Denver"}, headers={"Origin": "http://localhost"}).status_code == 200
    assert plain.get("/api/status").status_code == 200   # reading is fine; the host check covers other sites


def test_wrong_codes_are_rate_limited_and_rotate_the_code(env):
    from beacon import share as share_mod
    app, c = make_client(env)
    sh = sharing(app, "4821")
    for _ in range(share_mod.MAX_TRIES):
        assert "match. Check the Beacon screen" in c.get("/?code=1111", environ_base=GUEST).get_data(as_text=True)
    locked = c.get("/?code=4821", environ_base=GUEST)                    # even the right code, for now
    assert locked.status_code == 401 and "Too many wrong codes" in locked.get_data(as_text=True)
    assert c.get("/?code=4821", environ_base={"REMOTE_ADDR": "192.168.1.51"}).status_code == 302  # other devices fine
    for n in range(share_mod.ROTATE_AFTER):                              # someone sweeping from many addresses
        sh.check_code(f"10.0.0.{n}", "0000")
    assert sh.code != "4821" and sh.alert                                 # the code changed by itself


def test_guest_sessions_end_when_signed_out_or_stopped(env):
    app, c = make_client(env)
    sh = sharing(app, "4821")
    c.get("/?code=4821", environ_base=GUEST)
    assert c.get("/api/status", environ_base=GUEST).status_code == 200
    assert sh.status()["guests"] == 1
    sh.sign_out_all()
    assert c.get("/api/status", environ_base=GUEST).status_code == 401 and sh.code != "4821"
    c.get(f"/?code={sh.code}", environ_base=GUEST)
    assert c.get("/api/status", environ_base=GUEST).status_code == 200
    sh.server = None; sh.tokens.clear()                                  # what stop() does
    assert c.get("/api/status", environ_base=GUEST).status_code == 401


def test_security_headers_and_sandboxed_library_pages(env):
    _, c = make_client(env)
    r = c.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    page = r.get_data(as_text=True)
    assert "<script>" not in page and " on" + "click=" not in page                # nothing inline for the CSP to allow
    art = c.get("/read/kiwix/testbook/water")
    assert art.headers["Content-Security-Policy"].startswith("sandbox") and "script-src 'none'" in art.headers["Content-Security-Policy"]
    assert "connect-src 'none'" in c.get("/binder").headers["Content-Security-Policy"]
    assert "connect-src 'none'" in c.get("/read/book/reading/Test-Book.txt").headers["Content-Security-Policy"]
    (Path(env["cfg"]["manuals_dir"]) / "trap.html").write_text("<script>steal()</script>")
    trap = c.get("/read/manual/trap.html")
    assert trap.headers["Content-Disposition"].startswith("attachment")         # never runs as a Beacon page
    assert c.get("/api/status").headers["Cache-Control"] == "no-store"


def test_library_scripts_stay_inert_and_log_exports_are_formula_safe(env):
    import csv
    lib = KiwixLibrary(str(env["zim_dir"]))
    lib.article_html = lambda book, path: (b"fetch('/api/profile')", "application/javascript") if path.endswith(".js") else None
    app = create_app(dict(env["cfg"]), ollama=env["ollama"], kiwix=lib, manuals=env["manuals"], http=FakeHTTP(online=False))
    r = app.test_client().get("/read/kiwix/testbook/assets/app.js")
    assert r.mimetype == "text/plain" and r.headers["X-Content-Type-Options"] == "nosniff"   # a <script> tag can't run it
    audit = app.config["audit"]
    audit.notify = None
    audit.add("rejected-host", "192.168.1.9", "", '=HYPERLINK("http://evil.example","Open")', "alert")
    row = list(csv.reader(io.StringIO(audit.csv())))[-1]
    assert row[-1].startswith("'=HYPERLINK") and row[4] == "192.168.1.9"          # shown as text, never run


def test_requests_are_size_limited(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    assert c.post("/api/ask", data="x" * (3 * 1024 * 1024), content_type="application/json").status_code == 413
    ev = sse(c.post("/api/ask", json={"question": "boil " * 5000, "history": [{"role": "user", "content": "y" * 50000}] * 20}))
    assert ev[-1][0] == "done"
    sent = env["ollama"].last_messages
    assert len(sent[-1]["content"]) < 4000 + 20000 and all(len(m["content"]) <= 8000 for m in sent[1:-1])


def test_downloads_are_fingerprinted_and_checked_against_the_publisher(env, tmp_path):
    zim_bytes = (env["zim_dir"] / "testbook.zim").read_bytes()
    url = "https://download.kiwix.org/zim/other/mdwiki_en_all_maxi_2026-05.zim"
    good = hashlib.sha256(zim_bytes).hexdigest()
    new_zims = tmp_path / "zims"; new_zims.mkdir()
    env["cfg"]["zim_dir"] = str(new_zims)
    http = FakeHTTP({library.OPDS: OPDS, url + ".sha256": f"{good}  mdwiki_en_all_maxi_2026-05.zim\n", url: zim_bytes})
    app, c = make_client(env, http=http)
    c.post("/api/library/download", json={"ids": ["wikimed"]})
    app.config["downloader"].worker.join(10)
    job = app.config["downloader"].jobs["wikimed"]
    assert job["state"] == "done" and job["verified"] and job["sha256"] == good
    record = json.loads((Path(env["cfg"]["index_path"]).parent / "integrity.json").read_text())
    assert any(v["sha256"] == good and v["publisher_checked"] for v in record.values())
    # a tampered or corrupted download is thrown away
    (new_zims / "mdwiki_en_all_maxi_2026-05.zim").unlink()
    app2, c2 = make_client(env, http=FakeHTTP({library.OPDS: OPDS, url + ".sha256": "0" * 64, url: zim_bytes}))
    app2.config["installed"].map.clear()
    c2.post("/api/library/download", json={"ids": ["wikimed"]})
    app2.config["downloader"].worker.join(10)
    bad = app2.config["downloader"].jobs["wikimed"]
    assert bad["state"] == "failed" and "checksum" in bad["error"]
    assert not list(new_zims.glob("*.zim*"))


def test_integrity_check_spots_changed_files(tmp_path):
    f = tmp_path / "manual.pdf"; f.write_bytes(b"%PDF original")
    integ = library.Integrity(str(tmp_path / "integrity.json"), str(tmp_path))
    integ.record(f, library.sha256_file(f), "https://example.org/manual.pdf")
    assert integ.verify() == [{"file": "manual.pdf", "ok": True, "skipped": False}]
    f.write_bytes(b"%PDF changed by someone")
    assert integ.verify()[0]["ok"] is False
    res = checks.security({"ollama_url": "http://127.0.0.1:11435", "host": "127.0.0.1"}, {"encrypted": False}, integ, {"on": False})
    by = {r["name"]: r for r in res}
    assert by["AI engine is private"]["ok"] and by["Beacon itself is private"]["ok"]
    assert by["Drive encryption"]["warn"] and not by["Downloaded files unchanged"]["ok"]
    assert not checks.security({"ollama_url": "http://0.0.0.0:11434", "host": "127.0.0.1"}, {})[0]["ok"]


def test_health_check_knocks_on_its_own_ports_from_the_network_side():
    import socket
    exposed = socket.socket(); exposed.bind(("0.0.0.0", 0)); exposed.listen(1)   # like an engine listening on every network
    port = exposed.getsockname()[1]
    cfg = {"ollama_url": f"http://127.0.0.1:{port}", "host": "127.0.0.1", "port": port}
    try:
        res = {r["name"]: r for r in checks.security(cfg, {}, lan_ip="127.0.0.1")}
        assert not res["AI engine is private"]["ok"] and "Other devices can reach it" in res["AI engine is private"]["detail"]
    finally:
        exposed.close()
    res = {r["name"]: r for r in checks.security(cfg, {}, lan_ip="127.0.0.1")}
    assert res["AI engine is private"]["ok"] and "refuses connections" in res["AI engine is private"]["detail"]
    assert res["Beacon itself is private"]["ok"]


def test_household_info_can_be_erased(env, monkeypatch):
    _, c = make_client(env, monkeypatch=monkeypatch)
    c.post("/api/profile", json={"home": "Denver", "medical": "Dad: insulin"})
    path = Path(env["cfg"]["index_path"]).parent / "household.json"
    assert path.exists()
    assert c.post("/api/profile/erase", json={}).get_json() == {"erased": True}
    assert not path.exists() and c.get("/api/profile").get_json() == {}
    assert "Dad: insulin" not in c.get("/binder").get_data(as_text=True)


def test_health_check_includes_security(env, monkeypatch):
    import time
    _, c = make_client(env, monkeypatch=monkeypatch)
    c.post("/api/check", json={})
    for _ in range(50):
        r = c.get("/api/check").get_json()
        if r["report"] and not r["running"]:
            break
        time.sleep(0.1)
    sec = [x for x in r["report"]["results"] if x["kind"] == "security"]
    assert {x["name"] for x in sec} >= {"AI engine is private", "Beacon itself is private", "Wi-Fi sharing"}


# ------------------------------------------------------------------ connections monitor

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def test_device_names_from_browsers():
    from beacon.audit import describe
    assert describe(IPHONE) == "iPhone, Safari"
    assert describe("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36") == "Android phone, Chrome"
    assert describe("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15") == "Mac, Safari"
    assert describe("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0") == "Windows PC, Edge"
    assert describe("curl/8.7.1").startswith("Script or tool")
    assert describe("") == "Unknown device"


def test_connections_are_logged_and_alerted(env):
    app, c = make_client(env)
    audit = app.config["audit"]
    notes = []
    audit.notify = lambda title, msg: notes.append(msg)
    sharing(app, "4821")
    phone = {**GUEST, "HTTP_USER_AGENT": IPHONE}
    c.get("/?code=1111", environ_base=phone)                                   # a wrong code
    c.get("/?code=4821", environ_base=phone)                                   # then the right one
    c.post("/api/quit", json={}, environ_base=phone)                           # pokes at a host-only action
    c.get("/api/profile", headers={"Host": "evil.example"})                    # DNS-rebinding attempt
    app.test_client().post("/api/profile", data="x", content_type="text/plain")  # CSRF attempt
    view = c.get("/api/security").get_json()
    kinds = [e["kind"] for e in view["events"]]
    assert kinds == ["wrong-code", "signed-in", "host-only", "rejected-host", "blocked-request"]
    wrong = view["events"][0]
    assert wrong["device"] == "iPhone, Safari" and wrong["ip"] == "192.168.1.50" and wrong["level"] == "warn"
    assert view["unseen"] == 4 and notes                                         # alerts raised (rate limited)
    assert [s["device"] for s in view["sessions"]] == ["iPhone, Safari"] and view["sessions"][0]["active"]
    # the log survives a restart, and exports for a report
    lines = (Path(env["root"]) / "data" / "logs" / "security.log").read_text().splitlines()
    assert len(lines) == 5 and json.loads(lines[0])["kind"] == "wrong-code"
    csv_text = c.get("/api/security/log.csv").get_data(as_text=True)
    assert csv_text.startswith("time,level,event,device,ip") and "iPhone, Safari" in csv_text
    from beacon.audit import Audit
    assert [e["kind"] for e in Audit(str(Path(env["root"]) / "data" / "logs" / "security.log")).since(0)] == kinds
    # guests can't read the log; the host can mark alerts seen and sign one device out
    assert c.get("/api/security", environ_base=phone).status_code == 403
    assert c.post("/api/security/seen", json={}).get_json() == {"unseen": 0}
    sid = view["sessions"][0]["id"]
    assert c.post("/api/share/revoke", json={"id": sid}).get_json()["revoked"]
    assert c.get("/api/status", environ_base=phone).status_code == 401
    assert "signed-out" in [e["kind"] for e in c.get("/api/security/events?after=5").get_json()["events"]]


def test_security_log_never_holds_questions_or_answers(env, monkeypatch):
    app, c = make_client(env, monkeypatch=monkeypatch)
    sharing(app, "4821")
    c.get("/?code=4821", environ_base=GUEST)
    sse(c.post("/api/ask", json={"question": "where can my insulin stay cool"}, environ_base=GUEST))
    c.post("/api/board", json={"kind": "need", "name": "Unit 4B", "text": "out of insulin"}, environ_base=GUEST)
    log = (Path(env["root"]) / "data" / "logs" / "security.log").read_text()
    assert "signed-in" in log and "insulin" not in log and "Unit 4B" not in log


def test_repeated_attempts_are_counted_not_flooded(env):
    app, c = make_client(env)
    sharing(app, "4821")
    for _ in range(3):
        c.get("/?code=1111", environ_base=GUEST)
    ev = c.get("/api/security").get_json()["events"]
    assert len(ev) == 1 and ev[0]["count"] == 3
    for _ in range(3):
        c.get("/?code=2222", environ_base=GUEST)                                # 5th wrong code: locked out
    ev = c.get("/api/security").get_json()["events"]
    assert [e["kind"] for e in ev] == ["wrong-code", "locked-out", "locked-out"]
    assert ev[0]["count"] == 4 and ev[1]["detail"].startswith("Locked out") and ev[2]["detail"].startswith("Kept trying")
    other = {**GUEST, "HTTP_USER_AGENT": "curl/8.7.1"}                         # a different device at the same address
    app.config["share"].failures.clear()
    c.get("/?code=3333", environ_base=other)
    ev = c.get("/api/security").get_json()["events"]
    assert ev[-1]["kind"] == "wrong-code" and ev[-1]["count"] == 1 and ev[-1]["device"].startswith("Script or tool")


# ------------------------------------------------------------------ archive and PDFs

def test_pdfs_are_real_and_readable(env):
    from pypdf import PdfReader
    from beacon.pdf import markdown_pdf
    long = "## Water\n\n- Store **1 gallon** per person per day [1].\n\n| Item | Amount |\n|---|---|\n| Water | 14 gal |\n\n" + \
           "\n\n".join("Keep the radio on for updates and check on neighbors who live alone. " * 5 for _ in range(30))
    reader = PdfReader(io.BytesIO(markdown_pdf("Shelter in place — 2 weeks", long, "Springfield, October 10")))
    assert len(reader.pages) >= 2 and reader.metadata["/Title"] == "Shelter in place — 2 weeks"
    first = reader.pages[0].extract_text()
    assert "Store 1 gallon per person per day [1]." in first and "Item Amount" in first
    assert f"Page 1 of {len(reader.pages)}" in first
    _, c = make_client(env)
    r = c.post("/api/pdf", json={"title": "Boil water", "markdown": "Boil it for **1 minute** [1].",
                                 "sources": [{"book": "EPA guide", "title": "p. 2"}], "meta": "Today"})
    assert r.headers["Content-Type"] == "application/pdf" and 'filename="Beacon - Boil water.pdf"' in r.headers["Content-Disposition"]
    text = PdfReader(io.BytesIO(r.data)).pages[0].extract_text()
    assert "Boil it for 1 minute [1]." in text and "Sources" in text and "1. EPA guide, p. 2" in text
    assert c.post("/api/pdf", json={"title": "x", "markdown": " "}).status_code == 400


def test_plans_are_archived_privately_and_can_be_shared(env, monkeypatch):
    from pypdf import PdfReader
    app, c = make_client(env, monkeypatch=monkeypatch)
    ev = sse(c.post("/api/plan", json={"template": "winter-storm", "answers": {"location": "Denver"}}))
    saved = dict(ev)["saved"]
    assert saved["shared"] is False
    items = c.get("/api/archive").get_json()
    assert items[0]["id"] == saved["id"] and items[0]["kind"] == "plan" and items[0]["meta"]["location"] == "Denver"
    sharing(app, "4821")
    c.get("/?code=4821", environ_base=GUEST)
    assert c.get("/api/archive", environ_base=GUEST).get_json() == []                   # private: guests can't see it
    assert c.get(f"/archive/{saved['id']}", environ_base=GUEST).status_code == 404
    assert c.post(f"/api/archive/{saved['id']}/share", json={"shared": True}, environ_base=GUEST).status_code == 403
    assert c.post(f"/api/archive/{saved['id']}/share", json={"shared": True}).get_json()["shared"] is True
    assert [i["id"] for i in c.get("/api/archive", environ_base=GUEST).get_json()] == [saved["id"]]
    page = c.get(f"/archive/{saved['id']}", environ_base=GUEST)
    assert page.status_code == 200 and "Winter storm" in page.get_data(as_text=True) and "connect-src 'none'" in page.headers["Content-Security-Policy"]
    pdf = c.get(f"/archive/{saved['id']}.pdf", environ_base=GUEST)
    assert pdf.headers["Content-Type"] == "application/pdf" and "Winter storm" in PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text()
    assert c.post(f"/api/archive/{saved['id']}/delete", json={}, environ_base=GUEST).status_code == 403
    assert c.post(f"/api/archive/{saved['id']}/delete", json={}).get_json() == {"deleted": True}
    assert c.get("/api/archive").get_json() == []
    guest_plan = sse(c.post("/api/plan", json={"template": "winter-storm", "answers": {}}, environ_base=GUEST))
    assert "saved" not in dict(guest_plan)                                                 # guests choose to share


def test_guests_share_answers_with_limits(env):
    app, c = make_client(env)
    sharing(app, "4821")
    phone = {**GUEST, "HTTP_USER_AGENT": IPHONE}
    c.get("/?code=4821", environ_base=phone)
    r = c.post("/api/archive", json={"kind": "answer", "title": "Water", "markdown": "Boil it.", "shared": False}, environ_base=phone).get_json()
    assert r["shared"] is True                                                             # guests can only share
    item = c.get(f"/api/archive/{r['id']}").get_json()
    assert item["by"] == "guest" and item["device"] == "iPhone, Safari"
    for _ in range(9):
        c.post("/api/archive", json={"title": "x", "markdown": "y"}, environ_base=phone)
    assert c.post("/api/archive", json={"title": "x", "markdown": "y"}, environ_base=phone).status_code == 429
    for bad in ("../../etc/passwd", "20261010-120000-zzzzzz", "x"):
        assert c.get(f"/api/archive/{bad}").status_code == 404


# ------------------------------------------------------------------ community board and the mesh

def test_board_checkins_posts_and_moderation(env):
    app, c = make_client(env)
    sharing(app, "4821")
    phone = {**GUEST, "HTTP_USER_AGENT": IPHONE}
    other = {"REMOTE_ADDR": "192.168.1.77"}
    c.get("/?code=4821", environ_base=phone); c.get("/?code=4821", environ_base=other)
    assert c.post("/api/board", json={"kind": "checkin", "name": "", "status": "safe"}, environ_base=phone).status_code == 400
    c.post("/api/board", json={"kind": "checkin", "name": "The Garcias", "status": "safe", "text": "All 4 of us"}, environ_base=phone)
    c.post("/api/board", json={"kind": "checkin", "name": "Unit 4B", "status": "help", "text": "Out of insulin"}, environ_base=other)
    need = c.post("/api/board", json={"kind": "need", "text": "Need a <b>generator</b> for a fridge"}, environ_base=other).get_json()
    c.post("/api/board", json={"kind": "offer", "text": "Have 20 gallons of water"})                 # the host posts too
    view = c.get("/api/board", environ_base=phone).get_json()
    assert [r["name"] for r in view["roster"]] == ["Unit 4B", "The Garcias"]                      # help first
    assert view["posts"][0]["text"] == "Have 20 gallons of water" and "ip" not in view["posts"][0]  # guests don't see addresses
    assert any(p["text"] == "Need a <b>generator</b> for a fridge" for p in view["posts"])         # stored as text, escaped by the page
    host_view = c.get("/api/board").get_json()
    assert next(p for p in host_view["posts"] if p["kind"] == "need")["ip"] == "192.168.1.77"
    # only the author (or the host) can resolve; only the host can pin or remove
    assert c.post("/api/board/resolve", json={"id": need["id"]}, environ_base=phone).status_code == 403
    assert c.post("/api/board/resolve", json={"id": need["id"]}, environ_base=other).get_json() == {"resolved": True}
    assert c.post("/api/board/pin", json={"id": need["id"], "pinned": True}, environ_base=phone).status_code == 403
    assert c.post("/api/board/pin", json={"id": need["id"], "pinned": True}).get_json() == {"pinned": True}
    assert c.get("/api/board").get_json()["posts"][0]["id"] == need["id"]                         # pinned on top
    assert c.post("/api/board/remove", json={"id": need["id"]}, environ_base=other).status_code == 403
    assert c.post("/api/board/remove", json={"id": need["id"]}).get_json() == {"removed": True}
    spammer = app.test_client()                                    # its own cookies, like a separate phone
    spammer.environ_base.update({"REMOTE_ADDR": "192.168.1.90", "HTTP_X_BEACON": "1"})
    assert spammer.post("/api/board", json={"kind": "note", "text": "spam"}).status_code == 401   # not signed in
    spammer.get("/?code=4821")
    codes = [spammer.post("/api/board", json={"kind": "note", "text": "spam"}).status_code for _ in range(13)]
    assert codes == [200] * 12 + [429]
    from beacon.board import Board
    assert len(Board(str(Path(env["root"]) / "data" / "board.json")).posts) == len(c.get("/api/board").get_json()["posts"])


class FakeRadio:
    def __init__(self):
        self.sent, self.closed = [], False
        self.nodes = {"!a1b2c3d4": {"user": {"id": "!a1b2c3d4", "longName": "Ridge Relay", "shortName": "RDG"},
                                    "lastHeard": 1760100000, "snr": 7.5, "hopsAway": 1,
                                    "position": {"latitude": 39.80, "longitude": -104.90}, "deviceMetrics": {"batteryLevel": 88}}}
        self.my_position = None
    def sendText(self, text, destinationId="^all", channelIndex=0, **kw): self.sent.append((text, destinationId, channelIndex))
    def getMyNodeInfo(self):
        return {"user": {"longName": "Beacon Base", "shortName": "BCN"}, **({"position": self.my_position} if self.my_position else {})}
    def close(self): self.closed = True


def test_meshtastic_bridge_with_a_simulated_radio(env):
    import time
    app, c = make_client(env)
    mesh, radio = app.config["mesh"], FakeRadio()
    mesh.factory = lambda port, host: radio
    assert c.get("/api/mesh").get_json()["state"] == "off"
    c.post("/api/mesh/connect", json={"port": "/dev/cu.usbserial-0001"})
    for _ in range(50):
        if mesh.state == "connected":
            break
        time.sleep(0.02)
    st = c.get("/api/mesh").get_json()
    assert st["state"] == "connected" and st["me"] == "Beacon Base" and st["nodes"] == 1
    assert st["nodes_list"][0]["name"] == "Ridge Relay" and st["nodes_list"][0]["lat"] == 39.8
    # heard on the mesh -> the board; check-ins -> the roster, with a confirmation back to the sender
    mesh.on_receive({"decoded": {"text": "Road washed out at Elm St bridge"}, "fromId": "!a1b2c3d4", "channel": 0})
    mesh.on_receive({"decoded": {"text": "HELP Unit 4B: out of insulin"}, "fromId": "!a1b2c3d4", "channel": 1})
    mesh.on_receive({"decoded": {"text": "safe"}, "fromId": "!a1b2c3d4"})
    view = c.get("/api/board").get_json()
    mesh_post = next(p for p in view["posts"] if p["kind"] == "mesh")
    assert mesh_post["name"] == "Ridge Relay" and mesh_post["source"] == "mesh"
    assert {(r["name"], r["status"]) for r in view["roster"]} == {("Unit 4B", "help"), ("Ridge Relay", "safe")}
    assert radio.sent[0] == ("Beacon: checked in Unit 4B as NEEDS HELP.", "!a1b2c3d4", 1)
    # posts can go out over the mesh: the host always, guests only when allowed
    host_post = c.post("/api/board", json={"kind": "report", "name": "Base", "text": "Shelter open at the school", "mesh": True}).get_json()
    assert host_post["sent_mesh"] and radio.sent[-1] == ("Base: Shelter open at the school", "^all", 0)
    sharing(app, "4821"); c.get("/?code=4821", environ_base=GUEST)
    n = len(radio.sent)
    assert not c.post("/api/board", json={"kind": "note", "text": "hi", "mesh": True}, environ_base=GUEST).get_json()["sent_mesh"]
    assert c.post("/api/mesh/settings", json={"allow_guests": True}, environ_base=GUEST).status_code == 403
    c.post("/api/mesh/settings", json={"allow_guests": True})
    assert c.post("/api/board", json={"kind": "note", "text": "hi", "mesh": True}, environ_base=GUEST).get_json()["sent_mesh"]
    assert len(radio.sent) == n + 1
    long = c.post("/api/board", json={"kind": "note", "text": "x" * 500, "mesh": True}).get_json()
    assert len(radio.sent[-1][0]) <= 200 and len(long["text"]) == 500                          # the mesh gets a short version
    for bad in ("abc", "-1", "99"):                                                           # nonsense channels fall back to 0
        assert c.post("/api/board", json={"kind": "note", "text": "ch", "mesh": True, "channel": bad}).status_code == 200
        assert radio.sent[-1][2] == 0
    c.post("/api/mesh/disconnect", json={})
    assert radio.closed and mesh.state == "off" and not mesh.send("anyone?")
    assert c.post("/api/mesh/connect", json={"host": "bad host; rm -rf"}).status_code == 400


def test_mesh_reports_a_missing_radio_plainly(env):
    import time
    app, c = make_client(env)
    mesh = app.config["mesh"]
    def no_radio(port, host):
        raise OSError("[Errno 2] could not open port /dev/cu.usbserial-0001: No such file or directory")
    mesh.factory = no_radio
    c.post("/api/mesh/connect", json={})
    for _ in range(50):
        if mesh.state == "error":
            break
        time.sleep(0.02)
    st = c.get("/api/mesh").get_json()
    assert st["state"] == "error" and st["error"].startswith("No Meshtastic radio found")


# ------------------------------------------------------------------ supplies and new cards

def test_supplies_are_saved_for_the_host_only(env):
    app, c = make_client(env)
    assert c.get("/api/supplies").get_json() == {"people": 2, "items": []}
    body = {"people": 4, "items": [{"id": "a", "cat": "water", "name": "Water, gallons", "qty": 20, "gal": 1},
                                   {"id": "b", "cat": "food", "name": "Rice, 1 lb bag", "qty": "10", "kcal": 1650, "expires": "2027-03"},
                                   {"id": "c", "cat": "food", "name": "x" * 500, "qty": -5, "kcal": "lots"}, "junk"]}
    assert c.post("/api/supplies", json=body).get_json() == {"saved": True, "people": 4, "items": 3}
    got = c.get("/api/supplies").get_json()
    assert got["items"][1]["qty"] == 10 and len(got["items"][2]["name"]) == 80 and got["items"][2]["qty"] == 0
    assert c.post("/api/supplies", json={"people": "many"}).status_code == 400
    sharing(app, "4821"); c.get("/?code=4821", environ_base=GUEST)
    assert c.get("/api/supplies", environ_base=GUEST).status_code == 403


def test_new_cards_are_matched_and_well_formed():
    cards = ROOT / "library" / "manuals" / "cards"
    for card, _ in rag.CARD_KEYWORDS:
        text = (cards / card).read_text()
        assert text.startswith("# ") and "Sources:" in text, card
    assert rag.match_card("How long do we stay inside after a dirty bomb?") == "radiation-chemical-pandemic.md"
    assert rag.match_card("The water is off, what do we do about the toilet?") == "sanitation-and-hygiene.md"
    assert rag.match_card("How do I set up a meshtastic node for my street?") == "meshtastic.md"
    assert rag.match_card("Can a power station run my CPAP overnight?") == "off-grid-power.md"
    assert rag.match_card("How do we organize neighbors for mutual aid?") == "community-network.md"
    assert rag.match_card("Should I turn off Face ID before a checkpoint? Is my phone tracking me?") == "digital-safety.md"
    lib = library.load_catalog()
    assert lib["gear_list"]["groups"] and all(g["items"] for g in lib["gear_list"]["groups"])


# ------------------------------------------------------------------ your situation (setup questionnaire)

def test_situation_answers_are_cleaned():
    from beacon import situation as sitmod
    s = sitmod.clean({"phase": "now", "concerns": ["winter", "bogus", "outage"], "people": {"adults": "2", "children": 900, "x": 4},
                      "have": ["generator", "rocket launcher", "car"], "place": "  Denver,\n Colorado  ", "home": "castle",
                      "needs": "x" * 999})
    assert s["concerns"] == ["outage", "winter"] and s["have"] == ["generator", "car"]
    assert s["people"] == {"adults": 2, "children": 99, "elders": 0, "pets": 0}
    assert s["place"] == "Denver, Colorado" and s["home"] == "" and len(s["needs"]) == 300
    bare = sitmod.clean({"nothing": True, "have": ["generator", "skill_hunt"]})
    assert bare["have"] == ["skill_hunt"] and bare["nothing"]                      # "almost nothing" keeps only skills
    assert sitmod.is_empty(sitmod.clean({})) and not sitmod.is_empty(bare)


def test_next_steps_fit_the_situation():
    from beacon import situation as sitmod
    titles = {t["id"]: t["title"] for t in plans.TEMPLATES}
    cards = {f: label for f, label in __import__("beacon.cards", fromlist=["CARDS"]).CARDS}
    sit = {"phase": "now", "concerns": ["winter", "outage"], "people": {"adults": 2, "children": 1},
           "have": ["generator", "car", "first_aid"], "place": "Denver, Colorado"}
    r = sitmod.assess(sit, None, titles, cards, None)
    assert r["headline"] == "It's happening now: winter storm and power outage. 2 adults and 1 child in Denver, Colorado."
    assert r["first"][0]["action"] == {"type": "card", "id": "first-aid-essentials.md", "label": "First aid"}
    assert r["first"][1]["action"]["label"] == cards["power-outage.md"]                 # card names come from cards.py
    assert "carbon monoxide" in r["first"][1]["text"]                                  # generator, no CO alarm
    labels = [g["label"] for g in r["gaps"]]
    assert labels[0] == "Carbon monoxide alarm" and "First aid kit" not in labels
    water = next(g for g in r["gaps"] if g["label"] == "Water")
    assert "Store 9 gallons" in water["text"] and water["make_do"]                     # 3 people x 3 days
    assert [p["id"] for p in r["plans"]] == ["winter-storm", "power", "shelter-in-place"]       # the storm leads, then power
    assert {c["file"] for c in r["cards"]} >= {"first-aid-essentials.md", "power-outage.md", "severe-weather.md"}
    assert any(h["label"] == "Generator" and "Outdoors only" in h["text"] for h in r["have"])
    # starting with nothing: water first, and the make-do card leads
    bare = sitmod.assess({"phase": "now", "nothing": True}, None, titles, cards, None)
    assert "hidden water" in bare["first"][1]["text"] and bare["cards"][1]["file"] == "make-do.md"
    # living off the grid: homestead plan and farming items from the library
    lib = [{"id": "gardening-se", "title": "Gardening Q&A", "band": "grow-hunt", "rank": 1},
           {"id": "wikem", "title": "WikEM", "band": "medical", "rank": 1}]
    off = sitmod.assess({"phase": "ahead", "concerns": ["offgrid"]}, None, titles, cards, lib)
    assert off["plans"][0]["id"] == "homestead" and off["library"] == [{"id": "gardening-se", "title": "Gardening Q&A"}]
    # what's typed under special needs changes the advice
    cpap = sitmod.assess({"concerns": ["winter"], "needs": "Mom uses a CPAP and insulin"}, None, titles, cards, None)
    labels = [g["label"] for g in cpap["gaps"]]
    assert labels[0] == "Power for the medical device" and "Backup power" not in labels and "Insulin without a fridge" in labels
    # the library suggestions take turns between the topics that fit, so one big topic can't crowd out the rest
    many = [{"id": f"{b}-{i}", "title": b, "band": b, "rank": i} for b in ("medical", "shelter-winter", "civil-defense") for i in range(6)]
    mixed = sitmod.assess({"concerns": ["winter"], "needs": "insulin"}, None, titles, cards, many)["library"]
    assert [x["id"] for x in mixed[:3]] == ["shelter-winter-0", "medical-0", "civil-defense-0"] and len(mixed) == 8
    # a guest on the Wi-Fi can't fill in Your household on the Beacon computer
    guest = sitmod.assess({"phase": "ahead", "concerns": ["outage"]}, None, titles, cards, None, host=False)
    assert all(f["action"]["type"] != "household" for f in guest["first"]) and any(f["action"]["type"] == "paper" for f in guest["first"])
    # the supplies list counts as stored water and food
    sup = {"items": [{"cat": "water", "qty": 10, "gal": 1}, {"cat": "food", "qty": 30, "kcal": 1000}]}
    withsup = sitmod.assess({"people": {"adults": 1}}, sup, titles, cards, None)
    assert "Water" not in [g["label"] for g in withsup["gaps"]] and withsup["have"][0]["label"] == "Food"


def test_situation_is_private_and_shapes_answers(env, monkeypatch):
    app, c = make_client(env, monkeypatch=monkeypatch)
    assert c.post("/api/situation", json={"phase": "now", "concerns": ["winter"], "have": ["generator"], "needs": "Dad: insulin"}).get_json()["saved"]
    assert c.get("/api/situation").get_json()["needs"] == "Dad: insulin"
    sse(c.post("/api/ask", json={"question": "how do we stay warm"}))
    prompt = env["ollama"].last_messages[-1]["content"]
    assert "ABOUT THE PERSON ASKING" in prompt and "winter storm" in prompt and "Dad: insulin" in prompt
    sharing(app, "4821"); c.get("/?code=4821", environ_base=GUEST)
    assert c.get("/api/situation", environ_base=GUEST).get_json() == {}                       # the host's answers stay private
    assert c.post("/api/situation", json={"phase": "now"}, environ_base=GUEST).status_code == 403
    sse(c.post("/api/ask", json={"question": "how do we stay warm", "situation": {"concerns": ["heat"], "people": {"adults": 3}}},
               environ_base=GUEST))
    prompt = env["ollama"].last_messages[-1]["content"]
    assert "heat wave" in prompt and "3 adults" in prompt and "insulin" not in prompt         # the guest's own answers only
    guest_steps = c.post("/api/situation/assess", json={"situation": {"concerns": ["offgrid"]}}, environ_base=GUEST).get_json()
    assert guest_steps["library"] == [] and guest_steps["plans"][0]["id"] == "homestead"
    host_steps = c.post("/api/situation/assess", json={}).get_json()
    assert host_steps["first"][0]["action"]["id"] == "first-aid-essentials.md"
    assert c.get("/api/situation/options").get_json()["concerns"][0] == ["outage", "Power outage"]
    c.post("/api/profile/erase", json={})
    assert c.get("/api/situation").get_json()["phase"] == ""                                  # erased with the household


def test_cards_come_in_tab_order_with_short_names(env):
    _, c = make_client(env)
    cards_dir = Path(env["cfg"]["manuals_dir"]) / "cards"
    (cards_dir / "fire.md").write_text("# Fire Card\n\nTinder, kindling, fuel.\n")
    (cards_dir / "my-notes.md").write_text("# Neighborhood Notes Card\n\nOur street.\n")
    listed = c.get("/api/cards").get_json()
    assert [x["label"] for x in listed][:2] == ["First aid", "Fire"]
    assert listed[-1]["label"] == "Neighborhood Notes" and listed[-1]["path"] == "cards/my-notes.md"


# ------------------------------------------------------------------ updates from outside

NWS_JSON = json.dumps({"features": [{"properties": {
    "@id": "https://api.weather.gov/alerts/urn:oid:1", "event": "Winter Storm Warning", "severity": "Severe",
    "headline": "Winter Storm Warning issued October 10 until October 11 at 6:00AM MDT", "areaDesc": "Denver; Boulder",
    "description": "Heavy snow, 8 to 14 inches.", "instruction": "Travel could be very difficult.",
    "effective": "2026-10-10T12:00:00-06:00", "expires": "2099-10-11T06:00:00-06:00"}}]})
GDACS_RSS = """<?xml version="1.0"?><rss xmlns:gdacs="http://www.gdacs.org"><channel>
  <item><title>Red earthquake alert (Magnitude 7.4M) in Testland</title><description>&lt;b&gt;Strong&lt;/b&gt; shaking</description>
    <link>https://www.gdacs.org/report.aspx?eventid=1</link><pubDate>Sat, 10 Oct 2026 08:00:00 GMT</pubDate>
    <gdacs:alertlevel>Red</gdacs:alertlevel><gdacs:country>Testland</gdacs:country></item>
  <item><title>Green flood alert in Elsewhere</title><link>javascript:alert(1)</link><gdacs:alertlevel>Green</gdacs:alertlevel></item>
</channel></rss>"""
NEWS_RSS = """<?xml version="1.0"?><rss><channel><item><title>Grid operator asks for conservation</title>
  <link>https://example.org/news/1</link><pubDate>Sat, 10 Oct 2026 09:00:00 GMT</pubDate></item></channel></rss>"""
BOMB = """<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]><rss><channel><item><title>&lol2;</title></item></channel></rss>"""
FEEDS = [{"id": "nws", "title": "National Weather Service", "kind": "nws", "scope": "local", "country": "US",
          "url": "https://api.weather.gov/alerts/active?point={lat},{lon}"},
         {"id": "gdacs", "title": "GDACS disaster alerts", "kind": "rss", "scope": "world", "url": "https://gdacs.test/rss.xml"},
         {"id": "npr", "title": "NPR News", "kind": "rss", "scope": "news", "url": "https://npr.test/rss.xml"},
         {"id": "bad", "title": "Bad feed", "kind": "rss", "scope": "news", "url": "https://bad.test/rss.xml"}]


def test_updates_are_parsed_ranked_and_cached(tmp_path):
    from beacon.updates import Updates
    http = FakeHTTP({"https://api.weather.gov/alerts/active?point=39.74,-104.98": NWS_JSON, "https://gdacs.test/rss.xml": GDACS_RSS,
                     "https://npr.test/rss.xml": NEWS_RSS, "https://bad.test/rss.xml": BOMB})
    u = Updates(str(tmp_path / "updates.json"), FEEDS, http)
    v = u.refresh({"lat": 39.7392, "lon": -104.9847, "cc": "US", "label": "Denver, Colorado"})
    titles = [i["title"] for i in v["items"]]
    assert titles[0].startswith("Winter Storm Warning") and v["items"][0]["level"] == "alert"     # local alerts first
    assert titles[1].startswith("Red earthquake alert") and v["items"][1]["level"] == "alert"
    assert v["items"][1]["summary"] == "Strong shaking" and v["items"][1]["area"] == "Testland"   # HTML stripped
    assert next(i for i in v["items"] if i["title"].startswith("Green"))["url"] == ""              # only http(s) links
    assert "bad" in v["errors"] and "document type" in v["errors"]["bad"]                         # XML bombs refused
    from beacon.updates import _xml
    with pytest.raises(ValueError):                                                                # even after a long comment
        _xml(b'<?xml version="1.0"?><!--' + b"x" * 5000 + b'--><!DOCTYPE r [<!ENTITY a "b">]><rss/>')
    ctx = u.context()
    assert ctx.startswith("CURRENT UPDATES") and "Winter Storm Warning" in ctx and "Green flood" not in ctx
    assert Updates(str(tmp_path / "updates.json"), FEEDS, http).view()["items"][0]["feed"] == "nws"  # cached for offline
    abroad = Updates(str(tmp_path / "u2.json"), FEEDS, http).refresh({"lat": 48.85, "lon": 2.35, "cc": "FR", "label": "Paris"})
    assert all(i["feed"] != "nws" for i in abroad["items"])                                         # NWS covers the US only


def test_updates_are_opt_in_host_controlled_and_reach_the_ai(env, monkeypatch):
    import time
    http = FakeHTTP({library.OPDS: OPDS, "https://api.weather.gov/alerts/active?point=39.74,-104.98": NWS_JSON,
                     "https://gdacs.test/rss.xml": GDACS_RSS, "https://npr.test/rss.xml": NEWS_RSS, "https://bad.test/rss.xml": BOMB})
    app, c = make_client(env, http=http, monkeypatch=monkeypatch)
    app.config["updates"].feeds = FEEDS
    c.post("/api/situation", json={"place": "Denver"})
    first = c.get("/api/updates").get_json()
    assert first["auto"] is False and "online" not in first                      # off, and not even checking for internet
    assert c.post("/api/updates/settings", json={"auto": True}).get_json()["auto"] is True
    c.post("/api/updates/refresh", json={})
    for _ in range(50):
        if not app.config["updates"].checking and app.config["updates"].state["items"]:
            break
        time.sleep(0.05)
    assert c.get("/api/updates").get_json()["items"][0]["title"].startswith("Winter Storm Warning")
    sse(c.post("/api/ask", json={"question": "what should we do tonight"}))
    assert "CURRENT UPDATES" in env["ollama"].last_messages[-1]["content"]
    sharing(app, "4821"); c.get("/?code=4821", environ_base=GUEST)
    assert c.get("/api/updates", environ_base=GUEST).get_json()["items"]          # phones can read them
    assert c.post("/api/updates/refresh", json={}, environ_base=GUEST).status_code == 403
    assert c.post("/api/updates/settings", json={"auto": False}, environ_base=GUEST).status_code == 403


# ------------------------------------------------------------------ links between Beacons

class WSGIHTTP:
    """requests-like transport that delivers HTTP calls to Flask apps in this process."""
    class Resp:
        def __init__(self, r):
            self.status_code, self.headers, self._r = r.status_code, {"Set-Cookie": r.headers.get("Set-Cookie", "")}, r
        def json(self): return self._r.get_json()

    def __init__(self, routes):
        self.routes = routes  # base url -> (app, the caller's address as the app sees it)

    def _go(self, method, url, **kw):
        for base, (app, ip) in self.routes.items():
            if url.startswith(base):
                c = app.test_client(use_cookies=False)       # the Cookie header is set by the caller, like requests
                path = url[len(base):] or "/"
                return self.Resp(c.open(path, method=method, headers=kw.get("headers") or {}, json=kw.get("json"),
                                        environ_base={"REMOTE_ADDR": ip}))
        raise ConnectionError("no route")

    def get(self, url, headers=None, timeout=None, allow_redirects=True, **kw):
        return self._go("GET", url, headers=headers)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        return self._go("POST", url, headers=headers, json=json)


def test_linked_beacons_share_one_board(env, tmp_path, monkeypatch):
    import shutil as sh
    main_app, main = make_client(env)
    sub_root = tmp_path / "sub"; sh.copytree(env["root"], sub_root)
    sub_env = {**env, "root": sub_root, "cfg": {**env["cfg"], "data_root": str(sub_root),
               "index_path": str(sub_root / "data" / "idx.sqlite"), "manuals_dir": str(sub_root / "library" / "manuals")}}
    for f in ("board.json", "node.json", "links.json"):
        (sub_root / "data" / f).unlink(missing_ok=True)
    sub_app, sub = make_client(sub_env)
    assert main_app.config["links"].node["id"] != sub_app.config["links"].node["id"]
    sub_app.config["links"].http = WSGIHTTP({"http://192.168.1.20:8643": (main_app, "192.168.1.30")})
    monkeypatch.setattr(sub_app.config["links"], "start", lambda: None)            # sync by hand in the test
    sharing(main_app, "4821")
    main.post("/api/links/name", json={"name": "Main house"})
    sub.post("/api/links/name", json={"name": "Garcia house"})
    assert sub.post("/api/links", json={"url": "192.168.1.20:8643", "code": "1111"}).status_code == 400   # wrong code
    linked = sub.post("/api/links", json={"url": "192.168.1.20:8643", "code": "4821"}).get_json()
    assert linked["name"] == "Main house" and linked["node"] == main_app.config["links"].node["id"]
    main.post("/api/board", json={"kind": "checkin", "name": "Unit 4B", "status": "help", "text": "out of insulin"})
    sub.post("/api/board", json={"kind": "offer", "name": "Garcias", "text": "chainsaw and two strong backs"})
    sub_app.config["links"].sync_once()
    sub_app.config["links"].sync_once()                                            # twice: nothing doubles or echoes
    on_sub = sub.get("/api/board").get_json()
    on_main = main.get("/api/board").get_json()
    assert [r["name"] for r in on_sub["roster"]] == ["Unit 4B"]
    assert next(p for p in on_sub["posts"] if p["kind"] == "checkin")["via"] == "Main house"
    offer = next(p for p in on_main["posts"] if p["kind"] == "offer")
    assert offer["via"] == "Garcia house" and offer["source"] == "link"
    assert len(on_main["posts"]) == 2 and len(on_sub["posts"]) == 2
    # the main Beacon sees the link in Connections and can sign it out
    sess = main.get("/api/security").get_json()["sessions"]
    assert sess[0]["device"] == "Linked Beacon (Garcia house)"
    main.post("/api/share/revoke", json={"id": sess[0]["id"]})
    sub_app.config["links"].sync_once()
    assert "Signed out" in sub.get("/api/links").get_json()["links"][0]["error"]
    # what a linked Beacon sends is checked: real numbers for times, a known origin, a cap per device
    ml = main_app.config["links"]
    assert ml.receive([{"kind": "note", "text": "x", "origin": "abcdef12:0123456789", "t": float("nan")},
                       {"kind": "note", "text": "y", "origin": "abcdef12:0123456789a", "t": 1}, "junk"], "X") == 1
    strict = json.loads(main.get("/api/board").data, parse_constant=lambda c: pytest.fail(f"{c} in the Board's JSON"))
    assert all(time.time() - 86400 < p["t"] <= time.time() for p in strict["posts"])
    assert ml.receive([{"kind": "note", "text": f"spam {i}", "origin": f"abcdef12:{i:010x}"} for i in range(1, 40)], "X", limit=5) == 5
    # guests can't manage links, and pushed posts need a real Beacon id
    sharing(sub_app, "9999"); sub.get("/?code=9999", environ_base=GUEST)
    assert sub.get("/api/links", environ_base=GUEST).status_code == 403
    assert sub.post("/api/link/posts", json={"posts": []}, environ_base=GUEST).status_code == 403


def test_mesh_radio_plugs_and_plays_and_lends_its_gps(env):
    import time
    app, c = make_client(env)
    mesh, radio = app.config["mesh"], FakeRadio()
    radio.my_position = {"latitude": 39.7392, "longitude": -104.9903, "time": 1}
    mesh.factory = lambda port, host: radio
    assert not mesh.watch_once([])                                            # nothing plugged in
    assert mesh.watch_once(["/dev/cu.usbmodem1"])                              # plugged in: connects by itself
    for _ in range(50):
        if mesh.state == "connected":
            break
        time.sleep(0.02)
    st = c.get("/api/mesh").get_json()
    assert st["state"] == "connected" and st["auto"] and st["position"] == {"lat": 39.7392, "lon": -104.9903, "time": 1}
    c.post("/api/mesh/disconnect", json={})
    assert not mesh.watch_once(["/dev/cu.usbmodem1"])                          # a manual disconnect sticks...
    assert not mesh.watch_once([]) and mesh.watch_once(["/dev/cu.usbmodem1"])  # ...until the radio is replugged
    c.post("/api/mesh/settings", json={"auto": False})
    mesh.disconnect()
    assert not mesh.watch_once([]) and not mesh.watch_once(["/dev/cu.usbmodem2"])
    # the radio just plugged in wins over a port that was already there
    opened = []
    mesh.factory = lambda port, host: opened.append(port) or radio
    c.post("/api/mesh/settings", json={"auto": True})
    mesh._ports_seen = ["/dev/cu.usbserial-old"]
    assert mesh.watch_once(["/dev/cu.usbserial-old", "/dev/cu.usbmodem9"])
    for _ in range(50):
        if opened:
            break
        time.sleep(0.02)
    assert opened == ["/dev/cu.usbmodem9"]


def test_mesh_only_looks_at_usb_serial_ports(monkeypatch):
    from types import SimpleNamespace as NS
    lp = pytest.importorskip("serial.tools.list_ports")      # pyserial comes with the Meshtastic add-on
    from beacon import mesh as meshmod
    fake = [NS(device="/dev/cu.debug-console", vid=None), NS(device="/dev/cu.Bluetooth-Incoming-Port", vid=None),
            NS(device="/dev/ttyS0", vid=None), NS(device="/dev/tty.usbmodem1101", vid=0x239A),
            NS(device="/dev/cu.usbmodem1101", vid=0x239A), NS(device="/dev/ttyACM0", vid=0x303A)]
    monkeypatch.setattr(lp, "comports", lambda: fake)
    assert meshmod.serial_ports() == ["/dev/cu.usbmodem1101", "/dev/ttyACM0"]
