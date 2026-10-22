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
DOCS = BASE / "files"  # retained originals of searchable documents
MEDIA = BASE / "media"  # retained non-text assets for sharing
DB = BASE / "knowledge.db"
UPLOADS.mkdir(exist_ok=True)
IMAGES.mkdir(exist_ok=True)
DOCS.mkdir(exist_ok=True)
MEDIA.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
TEXT_FORMATS = {".txt", ".pdf", ".docx"}
IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
MEDIA_FORMATS = {
    ".gif", ".webp", ".bmp", ".mp4", ".m4v", ".mov", ".webm",
    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac",
    ".zip", ".csv", ".json", ".md", ".rtf", ".pptx", ".xlsx",
}
ALLOWED = TEXT_FORMATS | IMAGE_FORMATS | MEDIA_FORMATS

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
        db.execute("""
            CREATE TABLE IF NOT EXISTS media_assets (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                digest TEXT UNIQUE NOT NULL,
                stored_name TEXT NOT NULL,
                mimetype TEXT NOT NULL,
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
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
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
                "UPDATE documents SET name=?, stored_name=? "
                "WHERE id=? AND (stored_name IS NULL OR name<>?)",
                (original_name, stored_name, existing["id"], original_name),
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
            db.execute(
                "UPDATE visual_assets SET name=? WHERE id=?",
                (original_name, existing["id"]),
            )
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

def _safe_display_name(original_filename, requested_name):
    original = secure_filename(Path(original_filename).name)
    ext = Path(original).suffix.lower()
    requested = str(requested_name or "").strip()
    if not requested:
        return original
    # The extension is always inherited from the actual uploaded file.
    stem = secure_filename(Path(requested).stem).strip(" ._-")
    if not stem:
        raise ValueError("Enter a valid filename.")
    return f"{stem[:150]}{ext}"


def index_media(path, original_name):
    """Retain non-indexable files (GIF/video/audio/archives and other assets)."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stored_name = digest + path.suffix.lower()
    mimetype = _mime_for(original_name)
    destination = MEDIA / stored_name
    with connect() as db:
        existing = db.execute(
            "SELECT id FROM media_assets WHERE digest=?", (digest,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE media_assets SET name=?, mimetype=? WHERE id=?",
                (original_name, mimetype, existing["id"]),
            )
            return {
                "status": "already_exists",
                "name": original_name,
                "media_id": existing["id"],
                "shareable": True,
            }
        if not destination.exists():
            shutil.copy2(path, destination)
        cur = db.execute(
            "INSERT INTO media_assets(name, digest, stored_name, mimetype) "
            "VALUES (?, ?, ?, ?)",
            (original_name, digest, stored_name, mimetype),
        )
        return {
            "status": "retained",
            "name": original_name,
            "media_id": cur.lastrowid,
            "shareable": True,
            "mimetype": mimetype,
        }


@app.post("/api/upload")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Choose a file"), 400

    try:
        name = _safe_display_name(file.filename, request.form.get("display_name", ""))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error="Unsupported format. Try TXT, PDF, DOCX, common images, GIF, video, audio, ZIP, CSV, JSON, Markdown, PPTX or XLSX."), 400

    temp = UPLOADS / (hashlib.sha256(os.urandom(32)).hexdigest() + ext)
    file.save(temp)
    try:
        if ext in IMAGE_FORMATS:
            result = index_image(temp, name)
            return jsonify(result)
        if ext in TEXT_FORMATS:
            result = index_file(temp, name)
            return jsonify(result)
        result = index_media(temp, name)
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

@app.get("/api/media-assets")
def media_assets():
    with connect() as db:
        rows = db.execute(
            "SELECT id, name, mimetype, added_at FROM media_assets ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


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
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
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
            "kind": "image" if kind == "img" else ("media" if kind == "media" else "document"),
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

        # 1b) filename matches for retained non-indexable media.
        for media in db.execute(
            "SELECT id, name, stored_name, mimetype FROM media_assets"
        ).fetchall():
            n = sum(1 for t in terms if t in media["name"].lower())
            path = MEDIA / media["stored_name"]
            if n and path.is_file():
                add("media", media["id"], media["name"], path, "", n, 0.0)

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
        elif kind == "media":
            row = db.execute(
                "SELECT name, stored_name FROM media_assets WHERE id=?", (item_id,)
            ).fetchone()
            folder = MEDIA
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
