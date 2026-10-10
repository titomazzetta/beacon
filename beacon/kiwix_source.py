"""Full-text search over Kiwix .zim files (offline Wikipedia, WikiHow, iFixit, medical...).

Reads the .zim files directly with libzim, so kiwix-serve doesn't need to be running.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

try:
    from libzim.reader import Archive
    from libzim.search import Query, Searcher
    from libzim.suggestion import SuggestionSearcher
    HAVE_LIBZIM = True
except ImportError:  # pragma: no cover
    HAVE_LIBZIM = False


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "table", "sup"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "li", "h1", "h2", "h3", "h4", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


STOPWORDS = set("""a an the and or but if then so to of in on at by for with from about into over
after before under again how what when where why who whom which whose is are was were be been being do
does did doing have has had having i me my we our you your he she it its they them their this that these
those can could should would will shall may might must need want get got make long much many some any
there here just very really also not no yes up down out off right now please tell know think best way
safe safely""".split())


def keywords(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", question.lower())
    seen, out = set(), []
    for w in words:
        w = w.strip("'-")
        if len(w) > 2 and w not in STOPWORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def query_variants(question: str, limit: int = 8) -> list[str]:
    """The ZIM full-text engine ANDs every term, so natural questions often match nothing.
    Try all keywords, then pairs, then single words (longest = most specific first)."""
    kw = keywords(question)
    if not kw:
        return [question]
    variants = [" ".join(kw)]
    ranked = sorted(kw, key=len, reverse=True)
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            variants.append(f"{ranked[i]} {ranked[j]}")
    variants += ranked
    out = []
    for v in variants:
        if v not in out:
            out.append(v)
    return out[:limit]


class KiwixLibrary:
    def __init__(self, zim_dir: str):
        self.books: dict[str, "Archive"] = {}
        self.titles: dict[str, str] = {}
        if not HAVE_LIBZIM:
            return
        for path in sorted(Path(zim_dir).glob("*.zim")):
            try:
                self.books[path.stem] = Archive(str(path))
            except Exception as e:  # corrupt or partial download
                print(f"[kiwix] skipping {path.name}: {e}")
                continue
            try:
                self.titles[path.stem] = self.books[path.stem].get_metadata("Title").decode() or path.stem
            except Exception:
                self.titles[path.stem] = path.stem

    def summary(self) -> list[dict]:
        out = []
        for name, a in self.books.items():
            title = name
            try:
                title = a.get_metadata("Title").decode() or name
            except Exception:
                pass
            out.append({"id": name, "title": title, "articles": a.article_count,
                        "fulltext": a.has_fulltext_index})
        return out

    def reload(self, zim_dir: str):
        self.__init__(zim_dir)

    def random_title(self, book: str) -> str | None:
        """A random article title from one book (for the library check)."""
        archive = self.books.get(book)
        if not archive:
            return None
        for _ in range(25):
            try:
                entry = archive.get_random_entry()
                if not entry.is_redirect and "html" in entry.get_item().mimetype and len(entry.title) > 3:
                    return entry.title
            except Exception:
                continue
        return None

    def search(self, question: str, per_book: int = 2, max_chars: int = 2500,
               only: str | None = None) -> list[dict]:
        hits = []
        for name, archive in self.books.items():
            if only and name != only:
                continue
            paths = []
            try:
                for variant in query_variants(question):
                    if len(paths) >= per_book:
                        break
                    if archive.has_fulltext_index:
                        s = Searcher(archive).search(Query().set_query(variant))
                    else:  # no full-text index: fall back to title matching
                        s = SuggestionSearcher(archive).suggest(variant)
                    for p in s.getResults(0, per_book):
                        if p not in paths:
                            paths.append(p)
            except Exception as e:
                print(f"[kiwix] search failed in {name}: {e}")
            paths = paths[:per_book]
            for path in paths:
                try:
                    entry = archive.get_entry_by_path(path)
                    item = entry.get_item()
                    if "html" not in item.mimetype:
                        continue
                    text = html_to_text(bytes(item.content).decode("utf-8", "ignore"))
                except Exception:
                    continue
                if len(text) < 200:
                    continue
                hits.append({
                    "kind": "kiwix", "book": self.titles.get(name, name), "title": entry.title,
                    "ref": f"{name}/{path}", "text": text[:max_chars],
                })
        return hits

    def article_html(self, book: str, path: str) -> tuple[bytes, str] | None:
        archive = self.books.get(book)
        if not archive:
            return None
        try:
            item = archive.get_entry_by_path(path).get_item()
            return bytes(item.content), item.mimetype
        except KeyError:
            return None
