"""Your own PDFs / text manuals: chunked, embedded with Ollama, stored in SQLite.

Search combines vector similarity with keyword matching, so it still finds
exact terms ("FM 21-76", "tourniquet") that embeddings sometimes miss.
"""
import re
import sqlite3
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
    def __init__(self, db_path: str, ollama: Ollama, embed_model: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.ollama, self.embed_model = ollama, embed_model
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, chunks INT);
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY, file TEXT, page INT, text TEXT, vec BLOB);
            CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file);
        """)
        self._load_matrix()

    def _load_matrix(self):
        rows = self.db.execute("SELECT id, file, page, text, vec FROM chunks").fetchall()
        self.meta = [(r[0], r[1], r[2], r[3]) for r in rows]
        if rows:
            m = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
            self.matrix = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        else:
            self.matrix = None

    def _heading(self, file: str) -> str:
        """First markdown heading of a text manual, e.g. 'Safe Drinking Water Quick Card'."""
        cache = self.__dict__.setdefault("_headings", {})
        if file not in cache:
            title = Path(file).stem.replace("-", " ").title()
            try:
                for line in Path(file).read_text(errors="ignore").splitlines()[:20]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            except OSError:
                pass
            cache[file] = title
        return cache[file]

    def files(self) -> list[dict]:
        return [{"file": Path(p).name, "chunks": c}
                for p, _, c in self.db.execute("SELECT * FROM files ORDER BY path")]

    def ingest_dir(self, manuals_dir: str, progress=print) -> dict:
        root = Path(manuals_dir)
        seen, added, skipped = set(), 0, 0
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in SUPPORTED:
                continue
            key, mtime = str(path), path.stat().st_mtime
            seen.add(key)
            row = self.db.execute("SELECT mtime FROM files WHERE path=?", (key,)).fetchone()
            if row and row[0] == mtime:
                skipped += 1
                continue
            progress(f"Indexing {path.name}...")
            self.db.execute("DELETE FROM chunks WHERE file=?", (key,))
            pieces = [(pg, c) for pg, txt in extract_pages(path) for c in chunk(txt)]
            for i in range(0, len(pieces), 32):
                batch = pieces[i:i + 32]
                vecs = self.ollama.embed(self.embed_model, [c for _, c in batch])
                self.db.executemany(
                    "INSERT INTO chunks(file, page, text, vec) VALUES (?,?,?,?)",
                    [(key, pg, c, np.asarray(v, dtype=np.float32).tobytes())
                     for (pg, c), v in zip(batch, vecs)])
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (key, mtime, len(pieces)))
            self.db.commit()
            added += 1
        for (p,) in self.db.execute("SELECT path FROM files").fetchall():
            if p not in seen:  # file was deleted from the folder
                self.db.execute("DELETE FROM chunks WHERE file=?", (p,))
                self.db.execute("DELETE FROM files WHERE path=?", (p,))
        self.db.commit()
        self._load_matrix()
        return {"indexed": added, "unchanged": skipped, "total_chunks": len(self.meta)}

    def search(self, question: str, k: int = 4, max_chars: int = 2500) -> list[dict]:
        if self.matrix is None:
            return []
        q = np.asarray(self.ollama.embed(self.embed_model, [question])[0], dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-9
        scores = self.matrix @ q
        words = {w for w in re.findall(r"[a-z0-9\-]{4,}", question.lower())}
        if words:
            for i, (_, _, _, text) in enumerate(self.meta):
                t = text.lower()
                scores[i] += 0.03 * sum(w in t for w in words)
        out = []
        for i in np.argsort(-scores)[:k]:
            _, file, page, text = self.meta[i]
            title = f"p. {page}" if file.lower().endswith(".pdf") else self._heading(file)
            out.append({"kind": "manual", "book": Path(file).name, "title": title,
                        "ref": f"{Path(file).name}#page={page}", "text": text[:max_chars],
                        "score": float(scores[i])})
        return out
