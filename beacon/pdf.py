"""A small, dependency-free PDF writer for plans and answers.

Uses the PDF standard fonts (Helvetica, which every PDF reader has built in), wraps text,
breaks pages and numbers them. Understands the Markdown Beacon's AI writes: headings,
paragraphs, bullet and numbered lists, simple tables and **bold**.
"""
import re
import time

# Glyph widths (1/1000 em) for character codes 32-255 in WinAnsiEncoding.
_REG = [int(x) for x in (
    "278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,"
    "556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,"
    "469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,"
    "334,584,350,556,350,222,556,333,1000,556,556,333,1000,667,333,1000,350,611,350,350,222,222,333,333,350,556,1000,333,1000,500,"
    "333,944,350,500,667,278,333,556,556,556,556,260,556,333,737,370,556,584,333,737,333,400,584,333,333,333,556,537,278,333,333,"
    "365,556,834,834,834,611,667,667,667,667,667,667,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,"
    "722,722,722,722,667,667,611,556,556,556,556,556,556,889,500,556,556,556,556,278,278,278,278,556,556,556,556,556,556,556,584,"
    "611,556,556,556,556,500,556,500").split(",")]
_BOLD = [int(x) for x in (
    "278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,333,333,584,584,584,"
    "611,975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611,333,278,333,"
    "584,556,333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500,389,280,"
    "389,584,350,556,350,278,556,500,1000,556,556,333,1000,667,333,1000,350,611,350,350,278,278,500,500,350,556,1000,333,1000,556,"
    "333,944,350,500,667,278,333,556,556,556,556,280,556,333,737,370,556,584,333,737,333,400,584,333,333,333,611,556,278,333,333,"
    "365,556,834,834,834,611,722,722,722,722,722,722,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,"
    "722,722,722,722,667,667,611,556,556,556,556,556,556,889,556,556,556,556,556,278,278,278,278,611,611,611,611,611,611,611,584,"
    "611,611,611,611,611,556,611,556").split(",")]

W, H = 612, 792                 # US Letter, in points
LEFT, RIGHT, TOP, BOTTOM = 60, 60, 64, 64
BODY = 11
ASCII_FALLBACK = {"→": "->", "←": "<-", "≈": "~", "≤": "<=", "≥": ">=", "×": "x", "−": "-", "✓": "v", "✔": "v",
                  "✗": "x", "✘": "x", "‑": "-", " ": " ", " ": " ", " ": " ", "⚠": "!", "°": "°"}


def _enc(text: str) -> bytes:
    text = "".join(ASCII_FALLBACK.get(c, c) for c in text)
    return text.encode("cp1252", errors="replace")


def _width(data: bytes, bold: bool, size: float) -> float:
    table = _BOLD if bold else _REG
    return sum(table[b - 32] if 32 <= b <= 255 else 500 for b in data) * size / 1000


def _pdf_string(data: bytes) -> str:
    out = []
    for b in data:
        if b in (0x28, 0x29, 0x5C):          # ( ) \
            out.append("\\" + chr(b))
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _runs(text: str) -> list[tuple[str, bool]]:
    """'Use **plain** bleach' -> [('Use ', False), ('plain', True), (' bleach', False)]."""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(^|[^*\w])\*([^*\n]+)\*(?!\w)", r"\1\2", text)   # no italic face: plain
    out, bold = [], False
    for part in re.split(r"(\*\*)", text):
        if part == "**":
            bold = not bold
        elif part:
            out.append((part, bold))
    return out


def _blocks(md: str) -> list[tuple]:
    blocks, para = [], []

    def flush():
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()
    for raw in md.replace("\r", "").split("\n"):
        t = raw.strip()
        if not t or t.startswith("```"):
            flush()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", t)
        if m:
            flush(); blocks.append(("h", len(m.group(1)), m.group(2))); continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", t):
            flush(); blocks.append(("hr",)); continue
        if t.startswith("|") and t.endswith("|"):
            flush()
            if not re.fullmatch(r"\|[\s:|-]+\|", t):
                blocks.append(("tr", [c.strip() for c in t.strip("|").split("|")]))
            continue
        m = re.match(r"^([-*•]|\d+[.)])\s+(.*)", t)
        if m:
            flush()
            depth = 1 if len(raw) - len(raw.lstrip()) >= 2 else 0
            marker = "\x95" if not m.group(1)[0].isdigit() else m.group(1)
            blocks.append(("li", marker, m.group(2), depth)); continue
        if t.startswith(">"):
            t = t.lstrip("> ")
        para.append(t)
    flush()
    return blocks


class _Doc:
    def __init__(self):
        self.pages, self.ops, self.y = [], [], H - TOP

    def new_page(self):
        if self.ops:
            self.pages.append(self.ops)
        self.ops, self.y = [], H - TOP

    def need(self, height: float):
        if self.y - height < BOTTOM:
            self.new_page()

    def text(self, x: float, y: float, data: bytes, bold: bool, size: float, gray: float = 0):
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size:.1f} Tf {gray:.2f} g {x:.1f} {y:.1f} Td {_pdf_string(data)} Tj ET")

    @staticmethod
    def wrap(runs, size: float, width: float) -> list[list[tuple]]:
        """Break mixed bold/regular runs into lines no wider than `width`.
        Each line is a list of (bytes, bold, space_after, x)."""
        words = []                                   # [bytes, bold, space_after]
        for text, bold in runs:
            for piece in re.split(r"(\s+)", text):
                if not piece:
                    continue
                if piece.isspace():
                    if words:
                        words[-1][2] = True
                    continue
                words.append([_enc(piece), bold, False])
        space = {False: _width(b" ", False, size), True: _width(b" ", True, size)}
        lines, line, used = [], [], 0.0
        for data, bold, after in words:
            w = _width(data, bold, size)
            gap = space[line[-1][1]] if line and line[-1][2] else 0.0
            if line and used + gap + w > width:
                lines.append(line); line, used, gap = [], 0.0, 0.0
            line.append((data, bold, after, used + gap))
            used += gap + w
        if line:
            lines.append(line)
        return lines

    def line_at(self, ln, x0: float, y: float, size: float, gray: float = 0):
        """Words in the same font go out as one string with real spaces, so the PDF can be
        searched, copied and read aloud."""
        seg, seg_bold, seg_x = b"", None, 0.0
        for i, (data, bold, after, x) in enumerate(ln):
            if seg and bold == seg_bold:
                seg += (b" " if ln[i - 1][2] else b"") + data
            else:
                if seg:  # keep the space at a font change, so copied text reads right
                    self.text(x0 + seg_x, y, seg + (b" " if ln[i - 1][2] else b""), seg_bold, size, gray)
                seg, seg_bold, seg_x = data, bold, x
        if seg:
            self.text(x0 + seg_x, y, seg, seg_bold, size, gray)

    def flow(self, runs, size: float, x0: float, width: float, gap_after: float, first_prefix=None, gray: float = 0):
        lead = size * 1.42
        for n, ln in enumerate(self.wrap(runs, size, width)):
            self.need(lead)
            self.y -= lead
            if n == 0 and first_prefix is not None:
                self.text(x0 - 15, self.y, first_prefix[0], first_prefix[1], size, gray)
            self.line_at(ln, x0, self.y, size, gray)
        self.y -= gap_after

    def table(self, rows: list[list[str]], x0: float, width: float, size: float):
        """Columns of equal width; cells wrap; the first row is the header."""
        cols = max(len(r) for r in rows)
        colw = width / cols
        lead = size * 1.35
        for r, row in enumerate(rows):
            cells = [self.wrap([(re.sub(r"\*\*", "", c), r == 0)], size, colw - 8) for c in row]
            height = max(1, max(len(c) for c in cells)) * lead + 4
            self.need(height + 2)
            top = self.y
            for ci, lines in enumerate(cells):
                y = top
                for ln in lines:
                    y -= lead
                    self.line_at(ln, x0 + ci * colw, y, size)
            self.y = top - height
            weight = .6 if r == 0 else .25
            self.ops.append(f"{weight} w .6 G {x0:.1f} {self.y + 1:.1f} m {x0 + width:.1f} {self.y + 1:.1f} l S 0 G")
        self.y -= 6


def markdown_pdf(title: str, md: str, meta: str = "", footer: str = "Made offline by Beacon. Check critical steps against the sources.") -> bytes:
    doc = _Doc()
    doc.flow([(title, True)], 20, LEFT, W - LEFT - RIGHT, 2)
    if meta:
        doc.flow([(meta, False)], 10, LEFT, W - LEFT - RIGHT, 4, gray=.35)
    doc.ops.append(f"0.5 w {LEFT} {doc.y - 4:.1f} m {W - RIGHT} {doc.y - 4:.1f} l S")
    doc.y -= 14
    width = W - LEFT - RIGHT
    blocks = []
    for b in _blocks(md):                        # consecutive table rows become one table
        if b[0] == "tr" and blocks and blocks[-1][0] == "table":
            blocks[-1][1].append(b[1])
        elif b[0] == "tr":
            blocks.append(("table", [b[1]]))
        else:
            blocks.append(b)
    for b in blocks:
        kind = b[0]
        if kind == "h":
            size = {1: 16, 2: 14.5, 3: 12.5, 4: 11.5}[b[1]]
            doc.need(size * 3.2)                     # keep headings with what follows
            doc.y -= size * .45
            doc.flow([(t, True) for t, _ in _runs(b[2])], size, LEFT, width, 2)
        elif kind == "p":
            doc.flow(_runs(b[1]), BODY, LEFT, width, 5)
        elif kind == "li":
            indent = LEFT + 16 + 14 * b[3]
            prefix = (_enc(b[1]), b[1] != "\x95")
            if b[1] == "\x95":
                prefix = (b"\x95", False)
            doc.flow(_runs(b[2]), BODY, indent, W - RIGHT - indent, 2, first_prefix=prefix)
        elif kind == "table":
            doc.y -= 2
            doc.table(b[1], LEFT, width, BODY - 1)
        elif kind == "hr":
            doc.need(12); doc.y -= 6
            doc.ops.append(f"0.3 w {LEFT} {doc.y:.1f} m {W - RIGHT} {doc.y:.1f} l S")
            doc.y -= 6
    doc.new_page()
    return _assemble(doc.pages, title, footer)


def _assemble(pages: list[list[str]], title: str, footer: str) -> bytes:
    n = len(pages) or 1
    pages = pages or [[]]
    objs = []                                        # index 0 -> object 1
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for i, ops in enumerate(pages):
        foot = [f"BT /F1 8.5 Tf .45 g {LEFT} 36 Td {_pdf_string(_enc(footer))} Tj ET",
                f"BT /F1 8.5 Tf .45 g {W - RIGHT - _width(_enc(f'Page {i + 1} of {n}'), False, 8.5):.1f} 36 Td "
                f"{_pdf_string(_enc(f'Page {i + 1} of {n}'))} Tj ET"]
        stream = "\n".join(ops + foot).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>")
        objs.append(stream)
    utf16 = "<FEFF" + title.encode("utf-16-be").hex().upper() + ">"   # document info strings are Unicode
    info = f"<< /Title {utf16} /Producer (Beacon) /CreationDate (D:{time.strftime('%Y%m%d%H%M%S')}) >>"
    objs.append(info)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for num, obj in enumerate(objs, 1):
        offsets.append(len(out))
        if isinstance(obj, bytes):
            out += f"{num} 0 obj\n<< /Length {len(obj)} >>\nstream\n".encode() + obj + b"\nendstream\nendobj\n"
        else:
            out += f"{num} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
