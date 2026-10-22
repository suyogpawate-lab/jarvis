import mimetypes
import os
import re
import shutil
import sqlite3
import hashlib
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from flask import Flask, request, jsonify, render_template, abort, send_file
from pypdf import PdfReader
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
IMAGES = BASE / "images"
DOCS = BASE / "files"  # retained originals of TXT/PDF/DOCX uploads
DB = BASE / "knowledge.db"
UPLOADS.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)
DOCS.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
ALLOWED = {".txt", ".pdf", ".docx", ".jpg", ".jpeg", ".png"}

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                digest TEXT UNIQUE NOT NULL,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks
            USING fts5(document_id UNINDEXED, chunk_no UNINDEXED,
                       content, tokenize='unicode61')
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS visual_assets (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                digest TEXT UNIQUE NOT NULL,
                stored_name TEXT NOT NULL,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

    with connect() as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(documents)")]
        if "stored_name" not in cols:
            db.execute("ALTER TABLE documents ADD COLUMN stored_name TEXT")

def extract_text(path):
    ext = path.suffix.lower()
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if ext in {".jpg", ".jpeg", ".png"}:
        import subprocess
        result = subprocess.run(
            ["tesseract", str(path), "stdout"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or "Tesseract OCR failed").strip()
            raise ValueError(detail[:500])
        return result.stdout

    if ext == ".pdf":
        return "\n".join(page.extract_text() or ""
                         for page in PdfReader(str(path)).pages)
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(
            "".join(node.text or "" for node in para.findall(".//w:t", ns))
            for para in root.findall(".//w:p", ns)
        )
    raise ValueError("Unsupported file type")

def split_chunks(text, size=1200, overlap=150):
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        part = text[start:start + size]
        if part.strip():
            chunks.append(part)
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks

def index_file(path, original_name):
    text = extract_text(path)
    if not text.strip():
        raise ValueError("No extractable text found in this file")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pieces = split_chunks(text)

    stored_name = digest + path.suffix.lower()
    if not (DOCS / stored_name).exists():
        shutil.copy2(path, DOCS / stored_name)

    with connect() as db:
        existing = db.execute(
            "SELECT id FROM documents WHERE digest=?", (digest,)
        ).fetchone()
        if existing:
            # Re-uploading an older document backfills its sendable original.
            db.execute(
                "UPDATE documents SET stored_name=? "
                "WHERE id=? AND stored_name IS NULL",
                (stored_name, existing["id"]),
            )
            return {"status": "already_exists", "name": original_name}

        cur = db.execute(
            "INSERT INTO documents(name, digest, stored_name) VALUES (?, ?, ?)",
            (original_name, digest, stored_name)
        )
        doc_id = cur.lastrowid
        db.executemany(
            "INSERT INTO chunks(document_id, chunk_no, content) VALUES (?, ?, ?)",
            [(doc_id, i, chunk) for i, chunk in enumerate(pieces)]
        )
    return {"status": "indexed", "name": original_name, "chunks": len(pieces)}

def index_image(path, original_name):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ext = path.suffix.lower()
    stored_name = digest + ext
    destination = IMAGES / stored_name

    with connect() as db:
        existing = db.execute(
            "SELECT id FROM visual_assets WHERE digest=?", (digest,)
        ).fetchone()

        if existing:
            return {
                "status": "already_exists",
                "name": original_name,
                "image_id": existing["id"],
                "visual_available": True,
            }

    # Retain the original image even when OCR extracts no text.
    if not destination.exists():
        import shutil
        shutil.copy2(path, destination)

    try:
        text = extract_text(path).strip()
    except Exception:
        text = ""

    chunks_added = 0
    with connect() as db:
        cur = db.execute(
            "INSERT INTO visual_assets(name, digest, stored_name) "
            "VALUES (?, ?, ?)",
            (original_name, digest, stored_name),
        )
        image_id = cur.lastrowid

        if text:
            existing_doc = db.execute(
                "SELECT id FROM documents WHERE digest=?", (digest,)
            ).fetchone()

            if not existing_doc:
                doc = db.execute(
                    "INSERT INTO documents(name, digest) VALUES (?, ?)",
                    (original_name, digest),
                )
                doc_id = doc.lastrowid
                pieces = split_chunks(text)
                db.executemany(
                    "INSERT INTO chunks(document_id, chunk_no, content) "
                    "VALUES (?, ?, ?)",
                    [(doc_id, i, chunk) for i, chunk in enumerate(pieces)],
                )
                chunks_added = len(pieces)

    return {
        "status": "indexed",
        "name": original_name,
        "image_id": image_id,
        "visual_available": True,
        "ocr_text_found": bool(text),
        "chunks": chunks_added,
        "message": (
            "Image retained and OCR text indexed."
            if text else
            "Image retained. No useful text was extracted; visual analysis is still available."
        ),
    }

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/api/upload")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Choose a file"), 400

    name = secure_filename(file.filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error="Supported formats: TXT, PDF, DOCX, JPG, JPEG and PNG"), 400

    temp = UPLOADS / name
    file.save(temp)
    try:
        if ext in {".jpg", ".jpeg", ".png"}:
            result = index_image(temp, name)
            return jsonify(result)

        result = index_file(temp, name)
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=str(exc)), 400
    finally:
        temp.unlink(missing_ok=True)

@app.get("/api/documents")
def documents():
    with connect() as db:
        rows = db.execute("""
            SELECT d.id, d.name, d.added_at, COUNT(c.rowid) AS chunks
            FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
            GROUP BY d.id ORDER BY d.id DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/search")
def search():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify(results=[])

    # Convert plain-language words into safe FTS5 terms.
    import re
    terms = re.findall(r"[\w]+", query)
    if not terms:
        return jsonify(results=[])
    match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)

    with connect() as db:
        rows = db.execute("""
            SELECT d.name, c.content, c.chunk_no,
                   bm25(chunks) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE chunks MATCH ?
            ORDER BY score LIMIT 8
        """, (match,)).fetchall()

    return jsonify(results=[dict(r) for r in rows])

@app.get("/api/images")
def images():
    with connect() as db:
        rows = db.execute(
            "SELECT id, name, added_at FROM visual_assets ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.get("/api/image/<int:image_id>")
def image_file(image_id):
    with connect() as db:
        row = db.execute(
            "SELECT stored_name, name FROM visual_assets WHERE id=?",
            (image_id,),
        ).fetchone()

    if not row:
        return jsonify(error="Image not found"), 404

    path = IMAGES / row["stored_name"]
    if not path.is_file():
        return jsonify(error="Stored image file is missing"), 404

    return send_file(path, download_name=row["name"], conditional=True)

_STOP = {
    "the", "and", "for", "you", "your", "can", "could", "would", "please",
    "send", "share", "give", "get", "have", "has", "that", "this", "with",
    "from", "pic", "photo", "photos", "picture", "pictures", "image",
    "images", "file", "files", "doc", "document", "documents", "copy",
    "bhej", "bhejo", "mujhe", "hai", "kya", "tum", "aap",
}

_MIME_OVERRIDES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _mime_for(name):
    ext = Path(name).suffix.lower()
    return (
        _MIME_OVERRIDES.get(ext)
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )


def _query_terms(query):
    words = re.findall(r"\w+", str(query).lower())
    seen, terms = set(), []
    for word in words:
        if len(word) > 2 and word not in _STOP and word not in seen:
            seen.add(word)
            terms.append(word)
    return terms[:8]


def _resolve_sendable(db, doc_row):
    """Map a documents row to (kind, id, stored_path) or None."""
    if doc_row["stored_name"]:
        path = DOCS / doc_row["stored_name"]
        if path.is_file():
            return "doc", doc_row["id"], path
    # An image's OCR text lives in documents; its file is in visual_assets.
    asset = db.execute(
        "SELECT id, stored_name FROM visual_assets WHERE digest=?",
        (doc_row["digest"],),
    ).fetchone()
    if asset and (IMAGES / asset["stored_name"]).is_file():
        return "img", asset["id"], IMAGES / asset["stored_name"]
    return None


@app.post("/api/find-files")
def find_files():
    """Find retained originals (documents or images) matching a request."""
    data = request.get_json(silent=True) or {}
    terms = _query_terms(data.get("query", ""))
    if not terms:
        return jsonify(results=[])

    hits = {}  # (kind, id) -> dict

    def add(kind, item_id, name, path, snippet, name_hits, score):
        entry = hits.setdefault((kind, item_id), {
            "ref": f"{kind}:{item_id}",
            "kind": "image" if kind == "img" else "document",
            "id": item_id,
            "name": name,
            "mimetype": _mime_for(name),
            "size": path.stat().st_size,
            "snippet": "",
            "_name_hits": 0,
            "_score": 0.0,
        })
        entry["_name_hits"] = max(entry["_name_hits"], name_hits)
        entry["_score"] = min(entry["_score"], score)
        if snippet and not entry["snippet"]:
            entry["snippet"] = snippet

    with connect() as db:
        # 1) file-name matches
        for doc in db.execute(
            "SELECT id, name, digest, stored_name FROM documents"
        ).fetchall():
            n = sum(1 for t in terms if t in doc["name"].lower())
            if n:
                found = _resolve_sendable(db, doc)
                if found:
                    kind, item_id, path = found
                    add(kind, item_id, doc["name"], path, "", n, 0.0)

        for img in db.execute(
            "SELECT id, name, stored_name FROM visual_assets"
        ).fetchall():
            n = sum(1 for t in terms if t in img["name"].lower())
            path = IMAGES / img["stored_name"]
            if n and path.is_file():
                add("img", img["id"], img["name"], path, "", n, 0.0)

        # 2) content matches (any term, ranked by bm25)
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = db.execute("""
            SELECT d.id, d.name, d.digest, d.stored_name,
                   snippet(chunks, 2, '', '', ' ... ', 24) AS snip,
                   bm25(chunks) AS score
            FROM chunks JOIN documents d ON d.id = chunks.document_id
            WHERE chunks MATCH ?
            ORDER BY score LIMIT 20
        """, (match,)).fetchall()
        for row in rows:
            found = _resolve_sendable(db, row)
            if found:
                kind, item_id, path = found
                add(kind, item_id, row["name"], path,
                    (row["snip"] or "")[:200], 0, row["score"])

    ranked = sorted(
        hits.values(), key=lambda e: (-e["_name_hits"], e["_score"])
    )[:6]
    for entry in ranked:
        entry.pop("_name_hits", None)
        entry.pop("_score", None)
    return jsonify(results=ranked)


@app.get("/api/file/<kind>/<int:item_id>")
def file_download(kind, item_id):
    with connect() as db:
        if kind == "doc":
            row = db.execute(
                "SELECT name, stored_name FROM documents WHERE id=?", (item_id,)
            ).fetchone()
            folder = DOCS
        elif kind == "img":
            row = db.execute(
                "SELECT name, stored_name FROM visual_assets WHERE id=?", (item_id,)
            ).fetchone()
            folder = IMAGES
        else:
            return jsonify(error="Unknown file kind"), 404

    if not row or not row["stored_name"]:
        return jsonify(error="File not found"), 404

    path = (folder / row["stored_name"]).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        return jsonify(error="Stored file is missing"), 404

    return send_file(
        path, download_name=row["name"], mimetype=_mime_for(row["name"])
    )


@app.get("/health")
def health():
    return jsonify(status="ok", service="local-knowledge-hub")

if __name__ == "__main__":
    init_db()
    # Local device only; not exposed to the network.
    app.run(host="127.0.0.1", port=8766, debug=False)
