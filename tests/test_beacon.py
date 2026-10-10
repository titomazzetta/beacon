"""Run: python -m pytest -q   (no AI engine, no internet: both are faked)."""
import hashlib
import io
import json
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
        "Athens\tAthens\t33.96095\t-83.37794\tUS\tGeorgia\tUnited States\t127315\n"
        "Athens\tAthens\t37.98376\t23.72784\tGR\tAttica\tGreece\t664046\n"
        "Toronto\tToronto\t43.70011\t-79.4163\tCA\tOntario\tCanada\t2600000\n"
        "São Paulo\tSao Paulo\t-23.5475\t-46.63611\tBR\tSão Paulo\tBrazil\t10021295\n")
    (maps / "world.pmtiles").write_bytes(bytes(range(256)) * 40)
    cfg = {"ollama_url": "x", "chat_model": "", "embed_model": "nomic-embed-text",
           "zim_dir": str(zim_dir), "manuals_dir": str(man), "books_dir": str(root / "library" / "books"),
           "index_path": str(root / "data" / "idx.sqlite"), "data_root": str(root), "host": "127.0.0.1", "port": 1}
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
    return app, app.test_client()


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
    assert top["book"] == "radio.md" and top["title"].startswith("Radio") and top["ref"].startswith("radio.md")
    fire = idx.search("start a fire with tinder", k=1)[0]
    assert fire["ref"].startswith("sub/fire.txt")
    assert len(idx.samples()) == 2
    (d / "sub" / "fire.txt").unlink()
    idx.ingest_dir(str(d), progress=lambda m: None)
    assert [f["file"] for f in idx.files()] == ["radio.md"]


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
        elif it["type"] in ("pdf", "text"):
            assert it["url"].startswith("https://") and it["file"]
            assert "license" in it
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


# ------------------------------------------------------------------ plans, system, checks

def test_plan_build_includes_details():
    tpl = plans.get("leave-country")
    q, instr = plans.build(tpl, {"location": "Atlanta", "destination": "Italy", "documents": "US + IT passports"},
                           "Atlanta at 33.7, -84.4")
    assert "Leaving the country" in instr and "US + IT passports" in instr and "Atlanta at 33.7" in instr
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
    assert c.post("/api/profile", json={"home": "Atlanta", "medical": "Dad: insulin", "bogus": "x"}).get_json()["saved"]
    prof = c.get("/api/profile").get_json()
    assert prof == {"home": "Atlanta", "medical": "Dad: insulin"}
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
    assert idx2.search("NOAA radio", k=1)[0]["title"].startswith("Radio")
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
