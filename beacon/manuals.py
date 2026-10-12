"""Your own PDFs / text manuals: chunked, embedded with Ollama, stored in SQLite.

Search combines vector similarity with keyword matching, so it still finds
exact terms ("FM 21-76", "tourniquet") that embeddings sometimes miss.
"""
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .ollama_client import Ollama

SUPPORTED = {".pdf", ".txt", ".md"}
CHUNK_CHARS = 1200
OVERLAP = 200


def extract_pages(path: Path) -> list[tuple[int, str]]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    return [(1, path.read_text(errors="ignore"))]


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):  # try to break at a sentence
            dot = text.rfind(". ", start + size // 2, end)
            if dot != -1:
                end = dot + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


class ManualIndex:
    def __init__(self, db_path: str, ollama: Ollama, embed_model: str, root: str | None = None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.ollama, self.embed_model = ollama, embed_model
        self.root = Path(root) if root else None
        self.display: dict[str, str] = {}  # file -> the catalog's title for it, set by the app
        self.lock = threading.RLock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, chunks INT);
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY, file TEXT, page INT, text TEXT, vec BLOB);
            CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file);
            CREATE TABLE IF NOT EXISTS titles(path TEXT PRIMARY KEY, title TEXT);
        """)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(files)")}
        for col in ("pages", "chars"):  # added in v0.2
            if col not in cols:
                self.db.execute(f"ALTER TABLE files ADD COLUMN {col} INT DEFAULT 0")
        self.db.commit()
        self._load_matrix()

    def rel(self, file: str) -> str:
        """Path relative to the manuals folder. This is the key stored in the index, so the
        same drive works on a Mac (/Volumes/BEACON/...) and on Windows (E:\\...)."""
        p = Path(file)
        if self.root and p.is_absolute():
            try:
                return p.relative_to(self.root).as_posix()
            except ValueError:
                return p.as_posix()
        return p.as_posix()

    def abs(self, key: str) -> Path:
        p = Path(key)
        return p if p.is_absolute() or not self.root else self.root / p

    @staticmethod
    def _stamp(path: Path) -> str:
        st = path.stat()  # size + whole seconds: stable across macOS and Windows on exFAT
        return f"{st.st_size}:{int(st.st_mtime)}"

    def _load_matrix(self):
        with self.lock:
            rows = self.db.execute("SELECT id, file, page, text, vec FROM chunks ORDER BY id").fetchall()
        self.meta = [(r[0], r[1], r[2], r[3]) for r in rows]
        self.part, counts = {}, {}
        for cid, file, _, _ in self.meta:  # "part N of M" for text files with several passages
            counts[file] = counts.get(file, 0) + 1
            self.part[cid] = counts[file]
        self.parts_total = counts
        if rows:
            m = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
            self.matrix = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        else:
            self.matrix = None

    def _heading(self, file: str) -> str:
        """First markdown heading of a text manual, like 'Safe Drinking Water Card'."""
        cache = self.__dict__.setdefault("_headings", {})
        if file not in cache:
            title = Path(file).stem.replace("-", " ").title()
            try:
                for line in self.abs(file).read_text(errors="ignore").splitlines()[:20]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            except OSError:
                pass
            cache[file] = title
        return cache[file]

    def _title_of(self, file: str) -> str:
        if file.startswith("zim:"):
            return Path(file).stem
        if file.lower().endswith(".pdf"):
            return self.display.get(file) or self.pretty(file)
        return self.display.get(file) or self._heading(file)

    @staticmethod
    def pretty(file: str) -> str:
        """'army/FM-3-05-70_survival.pdf' -> 'FM 3 05 70 survival'."""
        return re.sub(r"[-_]+", " ", Path(file).stem).strip() or Path(file).name

    def files(self) -> list[dict]:
        out = []
        with self.lock:
            rows = self.db.execute("SELECT path, chunks, pages, chars FROM files ORDER BY path").fetchall()
            titles = dict(self.db.execute("SELECT path, title FROM titles").fetchall())
        for p, c, pages, chars in rows:
            scanned = (p.lower().endswith(".pdf") or p.startswith("zim:")) and pages and chars / max(pages, 1) < 40
            out.append({"file": Path(p).name, "path": p, "chunks": c, "title": titles.get(p, ""),
                        "pages": pages, "scanned": bool(scanned)})
        return out

    def pending(self, manuals_dir: str) -> list[str]:
        """Files in the folder that are new or changed since the last index."""
        out = []
        with self.lock:
            known = dict(self.db.execute("SELECT path, mtime FROM files").fetchall())
        for path in sorted(Path(manuals_dir).rglob("*")):
            if path.suffix.lower() not in SUPPORTED or path.name.startswith("._"):
                continue
            key = self.rel(str(path))
            if known.get(key) != self._stamp(path):
                out.append(key)
        return out

    def samples(self) -> list[tuple[str, str]]:
        """One passage from the middle of each indexed file (for the library check)."""
        by_file: dict[str, list[str]] = {}
        for _, file, _, text in self.meta:
            by_file.setdefault(file, []).append(text)
        return [(f, texts[len(texts) // 2]) for f, texts in by_file.items()]

    def ingest_dir(self, manuals_dir: str, progress=print) -> dict:
        root = Path(manuals_dir)
        seen, added, skipped = set(), 0, 0
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in SUPPORTED or path.name.startswith("._"):
                continue
            key, mtime = self.rel(str(path)), self._stamp(path)
            seen.add(key)
            with self.lock:
                row = self.db.execute("SELECT mtime FROM files WHERE path=?", (key,)).fetchone()
            if row and row[0] == mtime:
                skipped += 1
                continue
            progress(f"Indexing {path.name}...")
            try:
                pages = extract_pages(path)
            except Exception as e:  # damaged or encrypted PDF: skip it, keep going
                progress(f"Skipped {path.name}: {str(e)[:80]}")
                continue
            chars = sum(len(t.strip()) for _, t in pages)
            pieces = [(pg, c) for pg, txt in pages for c in chunk(txt)]
            vec_rows = []
            for i in range(0, len(pieces), 32):
                batch = pieces[i:i + 32]
                vecs = self.ollama.embed(self.embed_model, [c for _, c in batch])
                vec_rows += [(key, pg, c, np.asarray(v, dtype=np.float32).tobytes())
                             for (pg, c), v in zip(batch, vecs)]
            with self.lock:
                self.db.execute("DELETE FROM chunks WHERE file=?", (key,))
                self.db.executemany("INSERT INTO chunks(file, page, text, vec) VALUES (?,?,?,?)", vec_rows)
                self.db.execute("INSERT OR REPLACE INTO files(path, mtime, chunks, pages, chars) "
                                "VALUES (?,?,?,?,?)", (key, mtime, len(pieces), len(pages), chars))
                self.db.commit()
            added += 1
            continue
        with self.lock:
            for (p,) in self.db.execute("SELECT path FROM files").fetchall():
                if p not in seen and not p.startswith("zim:"):  # deleted from the folder (or an old key)
                    self.db.execute("DELETE FROM chunks WHERE file=?", (p,))
                    self.db.execute("DELETE FROM files WHERE path=?", (p,))
            self.db.commit()
        self._load_matrix()
        return {"indexed": added, "unchanged": skipped, "total_chunks": len(self.meta)}

    def ingest_zim_pdfs(self, kiwix, progress=print, max_entries: int = 50000) -> dict:
        """Some Kiwix archives (the "zimgit" collections) are bundles of PDF books that Kiwix's
        own search can't read. Pull the text out of those PDFs so the AI can use them."""
        import io
        from pypdf import PdfReader
        seen_books, added = set(), 0
        for book, archive in getattr(kiwix, "books", {}).items():
            seen_books.add(book)
            if archive.entry_count > max_entries:  # big encyclopedias have their own full-text search
                continue
            zim_path = Path(archive.filename) if hasattr(archive, "filename") else None
            stamp = f"{zim_path.stat().st_size}:{int(zim_path.stat().st_mtime)}" if zim_path and zim_path.exists() else "?"
            with self.lock:
                done = self.db.execute("SELECT COUNT(*) FROM files WHERE path LIKE ? AND mtime = ?",
                                       (f"zim:{book}/%", stamp)).fetchone()[0]
            if done:
                continue
            pdfs = []
            for i in range(archive.entry_count):
                try:
                    entry = archive._get_entry_by_id(i)
                    if entry.is_redirect:
                        continue
                    item = entry.get_item()
                    if item.mimetype == "application/pdf":
                        pdfs.append((entry.path, entry.title, item))
                except Exception:
                    continue
            if not pdfs:
                continue
            progress(f"Reading {len(pdfs)} PDFs inside {book}...")
            with self.lock:  # replace any older edition of this archive
                for (old,) in self.db.execute("SELECT path FROM files WHERE path LIKE ?", (f"zim:{book}/%",)).fetchall():
                    self.db.execute("DELETE FROM chunks WHERE file=?", (old,))
                    self.db.execute("DELETE FROM files WHERE path=?", (old,))
                self.db.commit()
            for path, title, item in pdfs:
                key = f"zim:{book}/{path}"
                try:
                    reader = PdfReader(io.BytesIO(bytes(item.content)))
                    pages = [(n + 1, pg.extract_text() or "") for n, pg in enumerate(reader.pages)]
                except Exception as e:
                    progress(f"Skipped {title}: {str(e)[:60]}")
                    continue
                pieces = [(pg, c) for pg, txt in pages for c in chunk(txt)]
                rows = []
                for j in range(0, len(pieces), 32):
                    batch = pieces[j:j + 32]
                    vecs = self.ollama.embed(self.embed_model, [c for _, c in batch])
                    rows += [(key, pg, c, np.asarray(v, dtype=np.float32).tobytes()) for (pg, c), v in zip(batch, vecs)]
                with self.lock:
                    self.db.executemany("INSERT INTO chunks(file, page, text, vec) VALUES (?,?,?,?)", rows)
                    self.db.execute("INSERT OR REPLACE INTO files(path, mtime, chunks, pages, chars) VALUES (?,?,?,?,?)",
                                    (key, stamp, len(pieces), len(pages), sum(len(t.strip()) for _, t in pages)))
                    self.db.execute("INSERT OR REPLACE INTO titles(path, title) VALUES (?, ?)", (key, title or Path(path).stem))
                    self.db.commit()
                added += 1
        with self.lock:  # archives that were removed from the drive
            for (p,) in self.db.execute("SELECT path FROM files WHERE path LIKE 'zim:%'").fetchall():
                if p.split("/", 1)[0][4:] not in seen_books:
                    self.db.execute("DELETE FROM chunks WHERE file=?", (p,))
                    self.db.execute("DELETE FROM files WHERE path=?", (p,))
            self.db.commit()
        self._load_matrix()
        return {"indexed": added, "total_chunks": len(self.meta)}

    def search(self, question: str, k: int = 4, max_chars: int = 2500) -> list[dict]:
        if self.matrix is None:
            return []
        q = np.asarray(self.ollama.embed(self.embed_model, [question])[0], dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-9
        scores = self.matrix @ q
        words = {w for w in re.findall(r"[a-z0-9\-]{4,}", question.lower())}
        if words:  # the question's words in a passage count a little, in its document's title a little more
            titles = {}
            for i, (_, file, _, text) in enumerate(self.meta):
                if file not in titles:
                    titles[file] = self._title_of(file).lower()
                t = text.lower()
                scores[i] += 0.03 * sum(w in t for w in words) + 0.05 * sum(w in titles[file] for w in words)
        out, per_file = [], {}
        for i in np.argsort(-scores):
            if len(out) >= k:
                break
            cid, file, page, text = self.meta[i]
            if per_file.get(file, 0) >= 2:  # at most two passages from one document, so others get a turn
                continue
            per_file[file] = per_file.get(file, 0) + 1
            if file.startswith("zim:"):  # a PDF book stored inside a Kiwix archive
                book, path = file[4:].split("/", 1)
                with self.lock:
                    row = self.db.execute("SELECT title FROM titles WHERE path=?", (file,)).fetchone()
                out.append({"kind": "zimpdf", "book": row[0] if row else Path(path).stem, "title": f"p. {page}",
                            "file": file, "ref": f"{book}/{path}", "page": page, "text": text[:max_chars],
                            "score": float(scores[i])})
                continue
            if file.lower().endswith(".pdf"):
                book, title = self.display.get(file) or self.pretty(file), f"p. {page}"
            else:
                book = self.display.get(file) or self._heading(file)
                title = f"part {self.part[cid]}" if self.parts_total.get(file, 1) > 1 else ""
            out.append({"kind": "manual", "book": book, "title": title, "file": file,
                        "ref": f"{file}#page={page}", "text": text[:max_chars],
                        "score": float(scores[i])})
        return out
