"""NotebookLM Clone — Phase 0/1/2-text backend (single-file scaffold).

Full modular layout per IMPLEMENTATION.md comes in Phase 5 refactor; this file
implements the same API contract with a lightweight TF-IDF retriever (no torch
needed) so the app runs immediately. Swap `retrieve()` for Chroma + MiniLM later.
"""
from __future__ import annotations

import asyncio
import contextvars
import csv
import datetime
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from rapidfuzz import fuzz

from . import auth, integrations, media, understanding, vectors


# ---------------- config ----------------
def _app_base():
    import sys as _sys
    if getattr(_sys, 'frozen', False):
        return Path(_sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE = _app_base()
STORAGE = Path(os.environ.get("STORAGE_DIR", str(BASE / "../../data"))).resolve()
STORAGE.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE / "app.db"
UPLOADS = STORAGE / "uploads"; UPLOADS.mkdir(exist_ok=True)
ARTIFACTS = STORAGE / "artifacts"; ARTIFACTS.mkdir(exist_ok=True)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock").lower()
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "edge").lower()

LIM_SOURCES = int(os.environ.get("LIMIT_SOURCES_PER_NOTEBOOK", "50"))
LIM_WORDS = int(os.environ.get("LIMIT_WORDS_PER_SOURCE", "500000"))
LIM_CHATS = int(os.environ.get("LIMIT_CHATS_PER_DAY", "50"))
LIM_STUDIO = int(os.environ.get("LIMIT_STUDIO_PER_DAY", "10"))
LIM_RESEARCH = int(os.environ.get("LIMIT_RESEARCH_PER_DAY", "10"))

CHUNK_WORDS = 600
CHUNK_OVERLAP = 90

app = FastAPI(title="NotebookLM Clone")


@app.exception_handler(404)
async def not_found_json(request, exc):
    return JSONResponse({"detail": "not found"}, 404)


@app.exception_handler(500)
async def server_error_json(request, exc):
    return JSONResponse({"detail": "internal error"}, 500)

# ---------------- db ----------------
def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks(id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, notebook_id TEXT, kind TEXT, title TEXT, uri TEXT,
  enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'ready', word_count INTEGER DEFAULT 0,
  char_count INTEGER DEFAULT 0, error TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, notebook_id TEXT, source_id TEXT, idx INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, notebook_id TEXT, role TEXT, content TEXT, citations_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, notebook_id TEXT, title TEXT, content_md TEXT, from_chat_id TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, notebook_id TEXT, kind TEXT, title TEXT, params_json TEXT,
  content_json TEXT, file_path TEXT, status TEXT DEFAULT 'done', created_at TEXT);
CREATE TABLE IF NOT EXISTS shares(id TEXT PRIMARY KEY, notebook_id TEXT, kind TEXT, token TEXT UNIQUE, artifact_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS usage(day TEXT, scope TEXT, counter TEXT, n INTEGER, PRIMARY KEY(day, scope, counter));
CREATE INDEX IF NOT EXISTS ix_chunks_nb ON chunks(notebook_id); CREATE INDEX IF NOT EXISTS ix_chunks_src ON chunks(source_id);
"""
MIGRATIONS = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, notebook_id TEXT, status TEXT, progress INTEGER, message TEXT, result_json TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_chunks_nb ON chunks(notebook_id);
CREATE INDEX IF NOT EXISTS ix_chunks_src ON chunks(source_id);
"""
with db() as c:
    c.executescript(SCHEMA)
    c.executescript(MIGRATIONS)
    auth.init_auth(c)
    integrations.init_integrations(c)
    c.execute("PRAGMA journal_mode=WAL")

def now(): return datetime.datetime.now(datetime.UTC).isoformat()
def nid(p=""): return (p or "") + uuid.uuid4().hex[:12]
def row2dict(r): return dict(r) if r else None

def check_quota(scope: str, counter: str, limit: int):
    day = datetime.date.today().isoformat()  # noqa: DTZ011 - quotas key on local calendar day by design
    with db() as c:
        r = c.execute("SELECT n FROM usage WHERE day=? AND scope=? AND counter=?", (day, scope, counter)).fetchone()
        n = r["n"] if r else 0
        if n >= limit:
            raise HTTPException(429, f"Daily {counter} limit reached ({limit}). Resets tomorrow.")
        c.execute("INSERT INTO usage(day,scope,counter,n) VALUES(?,?,?,1) ON CONFLICT(day,scope,counter) DO UPDATE SET n=n+1",
                  (day, scope, counter))
        who = _current_user.get()
        if who:
            auth.log_usage(c, who, counter)


_current_user: contextvars.ContextVar = contextvars.ContextVar("nb_user", default=None)

PUBLIC_API = ("/api/health", "/api/auth/", "/api/shares/", "/api/integrations/drive/callback")


def _token_from_request(request: Request):
    tok = request.cookies.get(auth.COOKIE)
    if not tok:
        ah = request.headers.get("authorization", "")
        if ah.lower().startswith("bearer "):
            tok = ah.split(None, 1)[1]
    return tok


def _notebook_of(path: str, method: str):
    # Returns (nbid_or_None, level). Centralized RBAC: read/write/admin.
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "notebooks" and parts[2]:
        nbid = parts[2]
        tail = "/".join(parts[3:])
        if method == "DELETE" and not tail:
            return nbid, "admin"
        if "members" in tail:
            return nbid, "admin"
        if method == "GET" or tail == "chat" or tail.startswith("chat") or tail == "duplicate":
            return nbid, "read"
        return nbid, "write"
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "artifacts":
        return "artifact:" + parts[2], ("read" if method == "GET" else "write")
    if path == "/api/demo:seed":
        return None, "write"
    if path == "/api/quotas:reset":
        return None, "admin"
    return None, "read"


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    _current_user.set(None)
    path = request.url.path
    if auth.AUTH_REQUIRED and path.startswith("/api/") and not path.startswith(PUBLIC_API):
        user = None
        tok = _token_from_request(request)
        if tok:
            with db() as c:
                user = auth.user_from_token(c, tok)
        if not user:
            return JSONResponse({"detail": "login required", "login_required": True}, status_code=401)
        _current_user.set(user["username"])
        request.state.user = user
        nbid, level = _notebook_of(path, request.method)
        if nbid and nbid.startswith("artifact:"):
            with db() as c:
                r = c.execute("SELECT notebook_id FROM artifacts WHERE id=?", (nbid[9:],)).fetchone()
                nbid = r["notebook_id"] if r else None
        if nbid:
            with db() as c:
                nb = c.execute("SELECT owner_id FROM notebooks WHERE id=?", (nbid,)).fetchone()
                if nb:
                    role = auth.member_role(c, nbid, user["id"])
                    if user["role"] == "admin" and not role:
                        role = "owner"
                    legacy_open = nb["owner_id"] is None and c.execute(
                        "SELECT COUNT(*) n FROM members WHERE notebook_id=?", (nbid,)).fetchone()["n"] == 0
                    if not auth.require_level(role, level, legacy_open):
                        return JSONResponse({"detail": f"{level} access required"}, status_code=403)
        elif level == "admin" and user["role"] != "admin":
            return JSONResponse({"detail": "admin required"}, status_code=403)
    return await call_next(request)

# ---------------- ingest ----------------
def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    out = []
    for i, pg in enumerate(PdfReader(str(path)).pages):
        t = pg.extract_text() or ""
        out.append(f"\n[page {i+1}]\n{t}")
    return "\n".join(out).strip()

def extract_docx(path: Path) -> str:
    import docx
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)

def extract_pptx(path: Path) -> str:
    from pptx import Presentation
    out = []
    for i, s in enumerate(Presentation(str(path)).slides):
        texts = [sh.text for sh in s.shapes if getattr(sh, "has_text_frame", False)]
        out.append(f"\n[slide {i+1}]\n" + "\n".join(texts))
    return "\n".join(out).strip()

def extract_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def fetch_url(url: str) -> str:
    r = httpx.get(url, timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]): t.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()

def fetch_youtube(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{6,})", url)
    if not m: raise ValueError("Could not parse YouTube video id")
    vid = m.group(1)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:  # new API (>=0.6)
            data = YouTubeTranscriptApi().fetch(vid)
            segs = data.segments if hasattr(data, "segments") else data
            return " ".join(getattr(s, "text", s.get("text", "") if isinstance(s, dict) else str(s)) for s in segs)
        except TypeError:
            segs = YouTubeTranscriptApi.get_transcript(vid)
            return " ".join(s.get("text", "") for s in segs)
    except Exception as e:
        raise ValueError(f"No captions/transcript available: {e}")

def chunk_text(text: str):
    words = text.split()
    chunks, i, idx = [], 0, 0
    while i < len(words):
        piece = words[i:i + CHUNK_WORDS]
        if not piece: break
        chunks.append((idx, " ".join(piece)))
        idx += 1
        i += CHUNK_WORDS - CHUNK_OVERLAP
    return chunks or [(0, text)]

def add_source_text(notebook_id: str, kind: str, title: str, uri: str, text: str) -> dict:
    text = re.sub(r"[ \t]+", " ", text).strip()
    wc = len(text.split())
    if wc > LIM_WORDS:
        text = " ".join(text.split()[:LIM_WORDS]); wc = LIM_WORDS
    sid = nid("s_")
    with db() as c:
        n = c.execute("SELECT COUNT(*) c FROM sources WHERE notebook_id=?", (notebook_id,)).fetchone()["c"]
        if n >= LIM_SOURCES: raise HTTPException(400, f"Source limit reached ({LIM_SOURCES})")
        c.execute("INSERT INTO sources(id,notebook_id,kind,title,uri,enabled,status,word_count,char_count,created_at) VALUES(?,?,?,?,?,1,'ready',?,?,?)",
                  (sid, notebook_id, kind, title, uri, wc, len(text), now()))
        rows = []
        for idx, piece in chunk_text(text):
            cid = nid("c_")
            c.execute("INSERT INTO chunks(id,notebook_id,source_id,idx,text) VALUES(?,?,?,?,?)", (cid, notebook_id, sid, idx, piece))
            rows.append((cid, sid, piece))
        saved = row2dict(c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())
    try:
        vectors.upsert(str(DB_PATH), notebook_id, rows)
    except Exception as e:
        print("embeddings upsert failed:", e)
    return saved

# ---------------- retrieval (TF-IDF, per-notebook) ----------------
def get_chunks(notebook_id: str, only_ids: list | None = None, enabled_only=True):
    with db() as c:
        if only_ids:
            q = f"SELECT ch.*, s.title stitle FROM chunks ch JOIN sources s ON s.id=ch.source_id WHERE ch.notebook_id=? AND ch.source_id IN ({','.join('?'*len(only_ids))}) ORDER BY ch.source_id, ch.idx"
            rows = c.execute(q, (notebook_id, *only_ids)).fetchall()
        elif enabled_only:
            rows = c.execute("SELECT ch.*, s.title stitle FROM chunks ch JOIN sources s ON s.id=ch.source_id WHERE ch.notebook_id=? AND s.enabled=1 AND s.status='ready' ORDER BY ch.source_id, ch.idx", (notebook_id,)).fetchall()
        else:
            rows = c.execute("SELECT ch.*, s.title stitle FROM chunks ch JOIN sources s ON s.id=ch.source_id WHERE ch.notebook_id=? ORDER BY ch.source_id, ch.idx", (notebook_id,)).fetchall()
        return [dict(r) for r in rows]

def retrieve(notebook_id: str, query: str, k=8, only_ids=None):
    chunks = get_chunks(notebook_id, only_ids)
    if not chunks:
        return []
    try:
        return vectors.search(str(DB_PATH), chunks, notebook_id, query, k)
    except Exception as e:
        print("vector search failed, using fallback:", e)
        qws = set(query.lower().split())

        def sc(t):
            ws = t.lower().split()
            return sum(1 for w in qws if w in ws)

        return sorted([{**c, "score": sc(c["text"])} for c in chunks], key=lambda x: -x["score"])[:k]


# ---------------- LLM ----------------
CHAT_SYS = ("You answer ONLY from the provided source passages. Every factual sentence must end with a citation like [1] or [2]. "
  "If the answer is not in the passages, reply exactly: \"I couldn't find this in your enabled sources.\" "
  "Never use outside knowledge. Return STRICT JSON: {\"answer_md\": \"...\", \"citations\": [{\"ref\": 1, \"source_id\": \"...\", \"quote\": \"exact short quote from passage\"}]}")

def llm_chat_json(system: str, user: str, max_tokens=2000) -> dict:
    if LLM_PROVIDER == "mock":
        raise RuntimeError("mock-call")  # handled by callers
    if LLM_PROVIDER == "ollama":
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json={"model": LLM_MODEL, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_predict": max_tokens}}, timeout=180)
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])
    # openai-compatible
    r = httpx.post(f"{OPENAI_BASE}/chat/completions", headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        json={"model": LLM_MODEL, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
              "max_tokens": max_tokens, "temperature": 0.2}, timeout=180)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

def verify_citations(citations: list, retrieved: list) -> list:
    by_src = {}
    for ch in retrieved: by_src.setdefault(ch["source_id"], []).append(ch)
    ok = []
    for c in citations or []:
        sid, quote = c.get("source_id", ""), (c.get("quote", "") or "")[:600]
        if not quote: continue
        best, best_ch = 0, None
        for ch in by_src.get(sid, retrieved):
            s = fuzz.partial_ratio(quote.lower(), ch["text"].lower()[:4000])
            if s > best: best, best_ch = s, ch
        if best >= 82 and best_ch:
            ok.append({"source_id": best_ch["source_id"], "source_title": best_ch.get("stitle", ""),
                       "chunk_id": best_ch["id"], "quote": quote, "ref": c.get("ref")})
    # renumber refs
    for i, c in enumerate(ok, 1): c["ref"] = i
    return ok

def mock_answer(query: str, retrieved: list) -> dict:
    if not retrieved:
        return {"answer_md": "I couldn't find this in your enabled sources.", "citations": []}
    def _stem(w):
        if len(w) > 4:
            if w.endswith("ies"):
                return w[:-3] + "y"
            for suf in ("ing", "es", "ed", "s"):
                if w.endswith(suf) and len(w) - len(suf) >= 3:
                    return w[:-len(suf)]
        return w
    qws = {_stem(w) for w in re.sub(r"[^a-z0-9 ]", "", query.lower()).split()}
    stop = {"what", "where", "when", "which", "who", "how", "does", "do", "is", "are", "the", "a", "an", "of", "in", "on", "to", "and"}
    qws -= stop
    scored = []
    for ch in retrieved[:4]:
        for s in re.split(r"(?<=[.!?])\s+", ch["text"]):
            s = s.strip()
            if len(s) < 20: continue
            sws = {_stem(w) for w in re.sub(r"[^a-z0-9 ]", "", s.lower()).split()}
            scored.append((len(qws & sws), s, ch))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 0
    if not scored or not qws or best < min(2, len(qws)):
        return {"answer_md": "I couldn't find this in your enabled sources.", "citations": []}
    tops = [s for s in scored if s[0] > 0][:2]
    parts, cits, seen = [], [], {}
    for score, sent, ch in tops:
        ref = seen.setdefault(ch["source_id"], len(seen) + 1)
        parts.append(f"{sent} [{ref}]")
    for sid, ref in seen.items():
        ch = next(c for _, _, c in tops if c["source_id"] == sid)
        quote = " ".join(s for _, s, c in tops if c["source_id"] == sid)[:400]
        cits.append({"ref": ref, "source_id": sid, "source_title": ch.get("stitle", ""),
                     "chunk_id": ch["id"], "quote": quote})
    cits.sort(key=lambda c: c["ref"])
    return {"answer_md": "\n\n".join(parts), "citations": cits}

def context_block(retrieved: list) -> str:
    return "\n\n".join(f"[{i+1}] (source_id={ch['source_id']} | {ch.get('stitle','')})\n{ch['text'][:2500]}" for i, ch in enumerate(retrieved))

# ---------------- API: health ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "llm_provider": LLM_PROVIDER, "model": LLM_MODEL,
            "embeddings": vectors.status(), "tts_provider": TTS_PROVIDER, "ffmpeg_ok": media.get_ffmpeg() is not None, "time": now(), "auth_required": auth.AUTH_REQUIRED, "google_configured": integrations.configured()}

# ---------------- API: auth + teams ----------------
@app.post("/api/auth/register")
async def api_register(req: Request):
    b = await req.json()
    with db() as c:
        try:
            u = auth.register(c, b.get("username", ""), b.get("password", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        tok = auth.login(c, u["username"], b.get("password", ""))
    resp = JSONResponse(u)
    resp.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax")
    return resp


@app.post("/api/auth/login")
async def api_login(req: Request):
    b = await req.json()
    with db() as c:
        tok = auth.login(c, b.get("username", ""), b.get("password", ""))
        if not tok:
            raise HTTPException(401, "invalid username or password")
        me = auth.user_from_token(c, tok)
    resp = JSONResponse(me)
    resp.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax")
    return resp


@app.post("/api/auth/logout")
def api_logout(req: Request):
    tok = _token_from_request(req)
    if tok:
        with db() as c:
            auth.logout(c, tok)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/auth/me")
def api_me(req: Request):
    tok = _token_from_request(req)
    me = None
    if tok:
        with db() as c:
            me = auth.user_from_token(c, tok)
    if auth.AUTH_REQUIRED and not me:
        raise HTTPException(401, "login required")
    return me or {"username": "local", "role": "admin", "local": True}


@app.get("/api/notebooks/{nbid}/members")
def nb_members(nbid: str):
    get_nb(nbid)
    with db() as c:
        rows = c.execute("SELECT m.role, u.id, u.username FROM members m JOIN users u ON u.id=m.user_id WHERE m.notebook_id=?", (nbid,)).fetchall()
        out = [dict(r) for r in rows]
        nb = row2dict(c.execute("SELECT owner_id FROM notebooks WHERE id=?", (nbid,)).fetchone())
        if nb and nb["owner_id"]:
            o = c.execute("SELECT id, username FROM users WHERE id=?", (nb["owner_id"],)).fetchone()
            if o:
                out.insert(0, {"id": o["id"], "username": o["username"], "role": "owner"})
        return out


@app.post("/api/notebooks/{nbid}/members")
async def nb_member_add(nbid: str, req: Request):
    get_nb(nbid)
    b = await req.json()
    role = b.get("role", "viewer")
    if role not in ("viewer", "editor"):
        raise HTTPException(400, "role must be viewer|editor")
    with db() as c:
        u = c.execute("SELECT id FROM users WHERE username=?", (b.get("username", "").strip(),)).fetchone()
        if not u:
            raise HTTPException(404, "user not found")
        c.execute("INSERT INTO members(notebook_id,user_id,role) VALUES(?,?,?) ON CONFLICT(notebook_id,user_id) DO UPDATE SET role=excluded.role", (nbid, u["id"], role))
        return {"added": b.get("username"), "role": role}


@app.delete("/api/notebooks/{nbid}/members/{uid}")
def nb_member_del(nbid: str, uid: str):
    with db() as c:
        c.execute("DELETE FROM members WHERE notebook_id=? AND user_id=?", (nbid, uid))
        return {"removed": uid}


@app.get("/api/analytics")
def api_analytics(days: int = 14):
    with db() as c:
        return auth.analytics(c, min(max(days, 1), 90))


# ---------------- API: google integrations ----------------
@app.get("/api/integrations/status")
def int_status(req: Request):
    origin = str(req.base_url).rstrip("/")
    with db() as c:
        connected = integrations.load_token(c) is not None
    return {"google_configured": integrations.configured(), "google_connected": connected,
            "redirect_uri": origin + "/api/integrations/drive/callback", "capabilities": integrations.capability_catalog()}


@app.get("/api/integrations/drive/auth-url")
def int_auth_url(req: Request):
    origin = str(req.base_url).rstrip("/")
    try:
        return {"url": integrations.auth_url(origin + "/api/integrations/drive/callback", origin)}
    except integrations.NotConfigured as e:
        raise HTTPException(400, str(e))


@app.get("/api/integrations/drive/callback")
def int_callback(req: Request, code: str = ""):
    origin = str(req.base_url).rstrip("/")
    if not code:
        raise HTTPException(400, "missing code (did you deny access?)")
    try:
        tok = integrations.exchange(code, origin + "/api/integrations/drive/callback")
    except integrations.NotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"exchange failed: {str(e)[:200]}")
    with db() as c:
        integrations.save_token(c, tok)
    return RedirectResponse("/?google=connected")


@app.get("/api/integrations/drive/files")
def int_files(req: Request, q: str = ""):
    origin = str(req.base_url).rstrip("/")
    try:
        with db() as c:
            return integrations.drive_files(c, origin, q)
    except integrations.NotConfigured as e:
        raise HTTPException(400, str(e))


@app.post("/api/notebooks/{nbid}/sources:drive")
async def src_drive(nbid: str, req: Request):
    get_nb(nbid)
    b = await req.json()
    file_id = (b.get("file_id") or "").strip()
    if not file_id:
        raise HTTPException(400, "file_id required")
    origin = str(req.base_url).rstrip("/")
    try:
        with db() as c:
            fname, kind, payload = integrations.drive_fetch(c, origin, file_id)
    except integrations.NotConfigured as e:
        raise HTTPException(400, str(e))
    if kind == "text":
        return add_source_text(nbid, "drive", fname[:80], f"drive:{file_id}", payload)
    dest_dir = UPLOADS / nbid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{nid()}_{Path(fname).name}"
    dest.write_bytes(payload)
    ext = (Path(fname).suffix or "").lower()
    try:
        if ext == ".pdf":
            text = extract_pdf(dest)
        elif ext == ".docx":
            text = extract_docx(dest)
        elif ext == ".pptx":
            text = extract_pptx(dest)
        else:
            text = extract_text_file(dest)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")
    if not text.strip():
        raise HTTPException(400, "No extractable text found in file")
    return add_source_text(nbid, "drive", fname[:80], f"drive:{file_id}", text)


@app.post("/api/artifacts/{aid}:sheets")
def art_sheets(aid: str, req: Request):
    with db() as c:
        a = row2dict(c.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone())
    if not a:
        raise HTTPException(404, "artifact not found")
    if a["kind"] != "datatable":
        raise HTTPException(400, "only data tables can go to Sheets")
    content = json.loads(a["content_json"] or "{}")
    origin = str(req.base_url).rstrip("/")
    try:
        with db() as c:
            url = integrations.sheets_push(c, origin, a["title"], content.get("columns", []), content.get("rows", []))
    except integrations.NotConfigured as e:
        raise HTTPException(400, str(e))
    return {"spreadsheet_url": url}


@app.post("/api/demo:seed")
def demo_seed():
    import seed_demo
    i = nid("nb_")
    with db() as c:
        c.execute("INSERT INTO notebooks(id,title,created_at,updated_at) VALUES(?,?,?,?)", (i, "Demo: Photosynthesis", now(), now()))
    for title, text in seed_demo.SOURCES:
        add_source_text(i, "paste", title, "", text)
    return {"id": i, "title": "Demo: Photosynthesis", "sources": len(seed_demo.SOURCES)}


# ---------------- API: notebooks ----------------
@app.get("/api/notebooks")
def list_nb(req: Request):
    user = getattr(req.state, "user", None)
    with db() as c:
        nbs = [dict(r) for r in c.execute("SELECT * FROM notebooks ORDER BY updated_at DESC").fetchall()]
        if auth.AUTH_REQUIRED and user and user["role"] != "admin":
            nbs = [n for n in nbs if n.get("owner_id") in (None, user["id"]) or
                   c.execute("SELECT 1 FROM members WHERE notebook_id=? AND user_id=?",
                             (n["id"], user["id"])).fetchone()]
        for n in nbs:
            n["sources_count"] = c.execute("SELECT COUNT(*) c FROM sources WHERE notebook_id=?", (n["id"],)).fetchone()["c"]
        return nbs

@app.post("/api/notebooks")
async def create_nb(req: Request):
    b = await req.json()
    i = nid("nb_")
    me = getattr(req.state, "user", None)
    owner = me["id"] if (auth.AUTH_REQUIRED and me) else None
    with db() as c:
        c.execute("INSERT INTO notebooks(id,title,created_at,updated_at,owner_id) VALUES(?,?,?,?,?)", (i, b.get("title", "Untitled notebook"), now(), now(), owner))
        return row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (i,)).fetchone())

@app.get("/api/notebooks/{nbid}")
def get_nb(nbid: str):
    with db() as c:
        n = row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (nbid,)).fetchone())
        if not n: raise HTTPException(404, "notebook not found")
        return n

@app.patch("/api/notebooks/{nbid}")
async def patch_nb(nbid: str, req: Request):
    b = await req.json()
    with db() as c:
        c.execute("UPDATE notebooks SET title=?, updated_at=? WHERE id=?", (b.get("title", "Untitled"), now(), nbid))
        return row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (nbid,)).fetchone())

@app.delete("/api/notebooks/{nbid}")
def del_nb(nbid: str):
    with db() as c:
        for t in ("chunks", "sources", "chats", "notes", "artifacts", "shares", "members"):
            c.execute(f"DELETE FROM {t} WHERE notebook_id=?", (nbid,))
        c.execute("DELETE FROM notebooks WHERE id=?", (nbid,))
    shutil.rmtree(UPLOADS / nbid, ignore_errors=True)
    vectors.delete_notebook(str(DB_PATH), nbid)
    return {"deleted": nbid}

@app.post("/api/notebooks/{nbid}/duplicate")
def duplicate_nb(nbid: str, req: Request):
    with db() as c:
        src = row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (nbid,)).fetchone())
        if not src:
            raise HTTPException(404, "notebook not found")
        new = nid("nb_")
        me = getattr(req.state, "user", None)
        owner = me["id"] if (auth.AUTH_REQUIRED and me) else None
        c.execute("INSERT INTO notebooks(id,title,created_at,updated_at,owner_id) VALUES(?,?,?,?,?)",
                  (new, (src["title"] or "Untitled") + " (copy)", now(), now(), owner))
        smap = {}
        for s in c.execute("SELECT * FROM sources WHERE notebook_id=?", (nbid,)).fetchall():
            sid2 = nid("s_")
            smap[s["id"]] = sid2
            c.execute("INSERT INTO sources(id,notebook_id,kind,title,uri,enabled,status,word_count,char_count,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (sid2, new, s["kind"], s["title"], s["uri"], s["enabled"], s["status"], s["word_count"], s["char_count"], s["error"], now()))
        rows = []
        for ch in c.execute("SELECT * FROM chunks WHERE notebook_id=?", (nbid,)).fetchall():
            cid2 = nid("c_")
            c.execute("INSERT INTO chunks(id,notebook_id,source_id,idx,text) VALUES(?,?,?,?,?)",
                      (cid2, new, smap.get(ch["source_id"], ch["source_id"]), ch["idx"], ch["text"]))
            rows.append((cid2, smap.get(ch["source_id"], ch["source_id"]), ch["text"]))
        for n in c.execute("SELECT * FROM notes WHERE notebook_id=?", (nbid,)).fetchall():
            c.execute("INSERT INTO notes(id,notebook_id,title,content_md,from_chat_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                      (nid("n_"), new, n["title"], n["content_md"], None, now(), now()))
    try:
        vectors.upsert(str(DB_PATH), new, rows)
    except Exception as e:
        print("duplicate embeddings failed:", e)
    with db() as c:
        return row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (new,)).fetchone())


@app.get("/api/notebooks/{nbid}/stats")
def stats(nbid: str):
    with db() as c:
        return {"sources": c.execute("SELECT COUNT(*) c FROM sources WHERE notebook_id=?", (nbid,)).fetchone()["c"],
                "chunks": c.execute("SELECT COUNT(*) c FROM chunks WHERE notebook_id=?", (nbid,)).fetchone()["c"],
                "words": c.execute("SELECT COALESCE(SUM(word_count),0) s FROM sources WHERE notebook_id=?", (nbid,)).fetchone()["s"],
                "chats": c.execute("SELECT COUNT(*) c FROM chats WHERE notebook_id=?", (nbid,)).fetchone()["c"],
                "notes": c.execute("SELECT COUNT(*) c FROM notes WHERE notebook_id=?", (nbid,)).fetchone()["c"],
                "artifacts": c.execute("SELECT COUNT(*) c FROM artifacts WHERE notebook_id=?", (nbid,)).fetchone()["c"]}

# ---------------- API: sources ----------------
@app.get("/api/notebooks/{nbid}/sources")
def list_src(nbid: str):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sources WHERE notebook_id=? ORDER BY created_at", (nbid,)).fetchall()]

@app.post("/api/notebooks/{nbid}/sources:file")
async def src_file(nbid: str, file: UploadFile = File(...)):  # noqa: B008 - standard FastAPI File() idiom
    get_nb(nbid)
    dest_dir = UPLOADS / nbid; dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{nid()}_{file.filename}"
    content = await file.read()
    if len(content) > 200 * 1024 * 1024: raise HTTPException(400, "File exceeds 200MB")
    dest.write_bytes(content)
    ext = (Path(file.filename).suffix or "").lower()
    try:
        if ext == ".pdf": text = extract_pdf(dest)
        elif ext == ".docx": text = extract_docx(dest)
        elif ext == ".pptx": text = extract_pptx(dest)
        elif ext in (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm"): text = extract_text_file(dest)
        else: text = extract_text_file(dest)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")
    if not text.strip(): raise HTTPException(400, "No extractable text found in file")
    kind = {"pdf": "pdf", ".pdf": "pdf"}.get(ext, ext.lstrip(".") or "file")
    return add_source_text(nbid, kind, file.filename, str(dest), text)

@app.post("/api/notebooks/{nbid}/sources:url")
async def src_url(nbid: str, req: Request):
    get_nb(nbid)
    url = (await req.json()).get("url", "").strip()
    if not url.startswith("http"): raise HTTPException(400, "Invalid URL")
    try: text = fetch_url(url)
    except Exception as e: raise HTTPException(400, f"Fetch failed: {e}")
    return add_source_text(nbid, "url", url[:80], url, text)

@app.post("/api/notebooks/{nbid}/sources:youtube")
async def src_yt(nbid: str, req: Request):
    get_nb(nbid)
    url = (await req.json()).get("url", "").strip()
    try: text = fetch_youtube(url)
    except Exception as e: raise HTTPException(400, str(e))
    return add_source_text(nbid, "youtube", url[:80], url, text)

@app.post("/api/notebooks/{nbid}/sources:paste")
async def src_paste(nbid: str, req: Request):
    get_nb(nbid)
    b = await req.json()
    if not (b.get("text") or "").strip(): raise HTTPException(400, "Empty text")
    return add_source_text(nbid, "paste", b.get("title", "Pasted text")[:80], "", b["text"])

@app.patch("/api/notebooks/{nbid}/sources/{sid}")
async def patch_src(nbid: str, sid: str, req: Request):
    b = await req.json()
    with db() as c:
        if "enabled" in b: c.execute("UPDATE sources SET enabled=? WHERE id=? AND notebook_id=?", (1 if b["enabled"] else 0, sid, nbid))
        if "title" in b: c.execute("UPDATE sources SET title=? WHERE id=? AND notebook_id=?", (b["title"][:120], sid, nbid))
        return row2dict(c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())

@app.delete("/api/notebooks/{nbid}/sources/{sid}")
def del_src(nbid: str, sid: str):
    with db() as c:
        c.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        c.execute("DELETE FROM sources WHERE id=? AND notebook_id=?", (sid, nbid))
    vectors.delete_source(str(DB_PATH), nbid, sid)
    return {"deleted": sid}

@app.get("/api/notebooks/{nbid}/sources/{sid}/preview")
def preview_src(nbid: str, sid: str, chars: int = 4000):
    with db() as c:
        rows = c.execute("SELECT text FROM chunks WHERE notebook_id=? AND source_id=? ORDER BY idx LIMIT 3", (nbid, sid)).fetchall()
        return {"text": "\n\n".join(r["text"] for r in rows)[:chars]}

# ---------------- API: chat ----------------
@app.get("/api/notebooks/{nbid}/chat")
def chat_hist(nbid: str, limit: int = 100):
    with db() as c:
        rows = c.execute("SELECT * FROM chats WHERE notebook_id=? ORDER BY created_at LIMIT ?", (nbid, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["citations"] = json.loads(d["citations_json"] or "[]"); out.append(d)
        return out

@app.post("/api/notebooks/{nbid}/chat")
async def chat(nbid: str, req: Request):
    get_nb(nbid)
    check_quota("global", "chats", LIM_CHATS)
    b = await req.json()
    msg = (b.get("message") or "").strip()
    if not msg: raise HTTPException(400, "Empty message")
    only = b.get("only_source_ids") or None
    note_pseudo = []
    for note_id in b.get("note_ids") or []:
        with db() as c:
            nn = row2dict(c.execute("SELECT * FROM notes WHERE id=? AND notebook_id=?", (note_id, nbid)).fetchone())
        if nn and (nn["content_md"] or "").strip():
            note_pseudo.append({"id": nn["id"], "source_id": f"note:{nn['id']}", "stitle": "\U0001f4dd " + (nn["title"] or "Note"),
                                "text": nn["content_md"][:4000], "score": 1.0})
    with db() as c:
        c.execute("INSERT INTO chats(id,notebook_id,role,content,citations_json,created_at) VALUES(?,?,?,?,?,?)",
                  (nid("m_"), nbid, "user", msg, "[]", now()))
    ret = retrieve(nbid, msg, k=8, only_ids=only)
    ret = (ret or []) + note_pseudo
    if LLM_PROVIDER == "mock":
        res = mock_answer(msg, ret)
    else:
        try:
            raw = llm_chat_json(CHAT_SYS, f"QUESTION:\n{msg}\n\nSOURCE PASSAGES:\n{context_block(ret) if ret else '(no enabled sources with matching content)'}")
            cits = verify_citations(raw.get("citations", []), ret)
            ans = raw.get("answer_md", "")
            if not cits and ret and "couldn't find" not in ans.lower():
                # unverifiable → fall back to extractive
                res = mock_answer(msg, ret)
            else:
                res = {"answer_md": ans, "citations": cits}
        except Exception as e:
            res = {"answer_md": f"_LLM error ({e}); showing extractive fallback:_\n\n" + mock_answer(msg, ret)["answer_md"],
                   "citations": mock_answer(msg, ret)["citations"]}
    with db() as c:
        mid = nid("m_")
        c.execute("INSERT INTO chats(id,notebook_id,role,content,citations_json,created_at) VALUES(?,?,?,?,?,?)",
                  (mid, nbid, "assistant", res["answer_md"], json.dumps(res["citations"]), now()))
        c.execute("UPDATE notebooks SET updated_at=? WHERE id=?", (now(), nbid))
        return {"id": mid, "answer_md": res["answer_md"], "citations": res["citations"]}

@app.post("/api/notebooks/{nbid}/chat:suggest")
async def suggest(nbid: str):
    chunks = get_chunks(nbid)[:6]
    if LLM_PROVIDER != "mock" and chunks:
        try:
            raw = llm_chat_json("Return STRICT JSON {\"prompts\": [\"...\",\"...\",\"...\"]} — 3 curious questions answerable from these passages.",
                                context_block(chunks))
            return {"prompts": raw.get("prompts", [])[:3]}
        except Exception: pass
    titles = list({c.get("stitle", "") for c in chunks})[:3]
    base = [
        "What are the key themes across my sources?",
        "Summarize the main arguments with supporting quotes.",
        "What important details might I have missed?",
    ]
    if titles: base[0] = f"What are the key themes in {titles[0]}?"
    return {"prompts": base}


@app.post("/api/notebooks/{nbid}/understanding")
async def understanding_agent(nbid: str, req: Request):
    """Recommend the next explanation format without making unsupported claims."""
    get_nb(nbid)
    body = await req.json()
    goal = (body.get("goal") or "").strip()
    passages = retrieve(nbid, goal or "key ideas", k=8, only_ids=body.get("only_source_ids") or None)
    if not passages:
        raise HTTPException(400, "Add or enable a source before asking the Understanding Agent.")
    return understanding.build_brief(goal, passages)

# ---------------- API: notes ----------------
@app.get("/api/notebooks/{nbid}/notes")
def list_notes(nbid: str):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM notes WHERE notebook_id=? ORDER BY updated_at DESC", (nbid,)).fetchall()]

@app.post("/api/notebooks/{nbid}/notes")
async def create_note(nbid: str, req: Request):
    b = await req.json()
    i = nid("n_")
    with db() as c:
        c.execute("INSERT INTO notes(id,notebook_id,title,content_md,from_chat_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (i, nbid, b.get("title", "Untitled note"), b.get("content_md", ""), b.get("from_chat_id"), now(), now()))
        return row2dict(c.execute("SELECT * FROM notes WHERE id=?", (i,)).fetchone())

@app.get("/api/notebooks/{nbid}/notes/{note_id}/pdf")
def note_pdf(nbid: str, note_id: str):
    with db() as c:
        n = row2dict(c.execute("SELECT * FROM notes WHERE id=? AND notebook_id=?", (note_id, nbid)).fetchone())
        if not n:
            raise HTTPException(404, "note not found")
    dest = ARTIFACTS / f"{nbid}_note_{note_id}.pdf"
    media.build_report_pdf(dest, n["title"] or "Note", n["content_md"] or "", [], meta="Note · NotebookLM Clone")
    return FileResponse(str(dest), media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.post("/api/notebooks/{nbid}/notes:from-chat")
async def note_from_chat(nbid: str, req: Request):
    b = await req.json()
    with db() as c:
        m = row2dict(c.execute("SELECT * FROM chats WHERE id=? AND notebook_id=?", (b.get("chat_id"), nbid)).fetchone())
        if not m: raise HTTPException(404, "chat message not found")
        cits = json.loads(m["citations_json"] or "[]")
        md = m["content"] + ("\n\n**Sources:** " + "; ".join(f"{c.get('source_title','')} (‘{c.get('quote','')[:80]}…’)" for c in cits) if cits else "")
        i = nid("n_")
        c.execute("INSERT INTO notes(id,notebook_id,title,content_md,from_chat_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (i, nbid, "Note from chat", md, m["id"], now(), now()))
        return row2dict(c.execute("SELECT * FROM notes WHERE id=?", (i,)).fetchone())

@app.patch("/api/notebooks/{nbid}/notes/{note_id}")
async def patch_note(nbid: str, note_id: str, req: Request):
    b = await req.json()
    with db() as c:
        c.execute("UPDATE notes SET title=?, content_md=?, updated_at=? WHERE id=? AND notebook_id=?",
                  (b.get("title", "Untitled"), b.get("content_md", ""), now(), note_id, nbid))
        return row2dict(c.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())

@app.delete("/api/notebooks/{nbid}/notes/{note_id}")
def del_note(nbid: str, note_id: str):
    with db() as c: c.execute("DELETE FROM notes WHERE id=? AND notebook_id=?", (note_id, nbid))
    return {"deleted": note_id}

# ---------------- API: studio (text tools) ----------------
def save_artifact(nbid, kind, title, params, content, file_path=""):
    i = nid("a_")
    with db() as c:
        c.execute("INSERT INTO artifacts(id,notebook_id,kind,title,params_json,content_json,file_path,status,created_at) VALUES(?,?,?,?,?,?,?,'done',?)",
                  (i, nbid, kind, title, json.dumps(params), json.dumps(content), file_path, now()))
        row = row2dict(c.execute("SELECT * FROM artifacts WHERE id=?", (i,)).fetchone())
    if kind == "mindmap" and not file_path:
        try:
            dest = ARTIFACTS / f"{nbid}_mindmap_{i}.png"
            media.render_mindmap_png(dest, (content or {}).get("root", "Mind map"), (content or {}).get("nodes", []))
            with db() as c:
                c.execute("UPDATE artifacts SET file_path=? WHERE id=?", (str(dest), i))
            row["file_path"] = str(dest)
        except Exception as e:
            print("mindmap png failed:", e)
    if kind == "report" and not file_path:
        try:
            dest = ARTIFACTS / f"{nbid}_report_{i}.pdf"
            media.build_report_pdf(dest, title, (content or {}).get("md", ""), (content or {}).get("citations", []))
            with db() as c:
                c.execute("UPDATE artifacts SET file_path=? WHERE id=?", (str(dest), i))
            row["file_path"] = str(dest)
        except Exception as e:
            print("report pdf failed:", e)
    return row

def studio_context(nbid, k=12):
    chunks = get_chunks(nbid)
    if not chunks: raise HTTPException(400, "Add at least one enabled source first")
    # diversity: round-robin across sources
    by_src: dict[str, list] = {}
    for c in chunks: by_src.setdefault(c["source_id"], []).append(c)
    picked, i = [], 0
    while len(picked) < min(k, len(chunks)):
        added = False
        for s in by_src.values():
            if i < len(s): picked.append(s[i]); added = True
        if not added: break
        i += 1
    return picked, context_block(picked)

# ---------------- jobs (background + SSE) ----------------
def job_update(jid, status, progress, message="", result=None):
    with db() as c:
        c.execute("UPDATE jobs SET status=?, progress=?, message=?, result_json=?, updated_at=? WHERE id=?",
                  (status, int(progress), (message or "")[:300], json.dumps(result or {}), now(), jid))

@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    with db() as c:
        r = row2dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
    if not r:
        raise HTTPException(404, "job not found")
    r["result"] = json.loads(r["result_json"] or "{}")
    return r

@app.get("/api/jobs/{jid}/stream")
async def job_stream(jid: str):
    from fastapi.responses import StreamingResponse

    async def gen():
        while True:
            with db() as c:
                r = row2dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
            if not r:
                yield 'event: error\ndata: {"message": "not found"}\n\n'
                return
            payload = {"status": r["status"], "progress": r["progress"], "message": r["message"] or ""}
            if r["status"] in ("done", "error"):
                payload["result"] = json.loads(r["result_json"] or "{}")
                yield f"data: {json.dumps(payload)}\n\n"
                return
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def run_bg(kind_label, nbid, coro_factory):
    jid = nid("j_")
    with db() as c:
        c.execute("INSERT INTO jobs(id,kind,notebook_id,status,progress,message,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?, ?,?)",
                  (jid, kind_label, nbid, "queued", 0, "queued", "{}", now(), now()))

    def runner():
        try:
            job_update(jid, "running", 1, "started")
            res = asyncio.run(coro_factory(lambda f, m: job_update(jid, "running", int(f * 100), m)))
            if isinstance(res, dict) and kind_label.startswith("studio:") and "id" in res:
                res = {"artifact_id": res["id"]}
            job_update(jid, "done", 100, "done", res)
        except Exception as e:
            job_update(jid, "error", 0, str(e)[:300])

    threading.Thread(target=runner, daemon=True).start()
    return {"job_id": jid}

async def studio_impl(nbid: str, kind: str, params: dict, prog=None):
    def P(f, m):
        if prog:
            prog(f, m)
    P(0.05, "retrieving sources")
    picked, ctx = studio_context(nbid)
    P(0.2, "generating")
    try:
        if kind == "report":
            rtype = params.get("type", "briefing")
            if LLM_PROVIDER == "mock": raise RuntimeError("mock")
            raw = llm_chat_json("Return STRICT JSON {\"md\": \"report markdown with [n] citations\", \"citations\": [{\"ref\":n,\"source_id\":\"...\",\"quote\":\"...\"}]}",
                f"Write a {rtype} report from these passages. Sections + bullets, every bullet cited.\n\n{ctx}")
            content = {"md": raw.get("md", ""), "citations": verify_citations(raw.get("citations", []), picked)}
            return save_artifact(nbid, kind, f"{rtype.title()} report", params, content)
        if kind == "flashcards":
            n, diff, topic = int(params.get("count", 10)), params.get("difficulty", "mixed"), params.get("topic", "key concepts")
            if LLM_PROVIDER == "mock": raise RuntimeError("mock")
            raw = llm_chat_json("Return STRICT JSON {\"cards\": [{\"front\":\"...\",\"back\":\"...\",\"source_id\":\"...\"}]}",
                f"Generate exactly {n} flashcards ({diff}) about {topic} from these passages.\n\n{ctx}")
            return save_artifact(nbid, kind, f"Flashcards ×{n}", params, {"cards": raw.get("cards", [])})
        if kind == "quiz":
            n = int(params.get("count", 5))
            if LLM_PROVIDER == "mock": raise RuntimeError("mock")
            raw = llm_chat_json("Return STRICT JSON {\"questions\": [{\"q\":\"...\",\"type\":\"mcq\",\"choices\":[\"..\",\"..\",\"..\",\"..\"],\"answer\":0,\"explanation\":\"...\",\"source_id\":\"...\"}]}",
                f"Generate {n} multiple-choice questions with 4 choices, answer index, explanation.\n\n{ctx}")
            return save_artifact(nbid, kind, f"Quiz ×{n}", params, {"questions": raw.get("questions", [])})
        if kind == "mindmap":
            if LLM_PROVIDER == "mock": raise RuntimeError("mock")
            raw = llm_chat_json("Return STRICT JSON {\"root\": \"...\", \"nodes\": [{\"id\":\"a\",\"label\":\"...\",\"children\":[\"b\"]}]} (max 30 nodes)",
                f"Extract a mind map (central topic + branches) from these passages.\n\n{ctx}")
            return save_artifact(nbid, kind, "Mind map", params, raw)
        if kind == "datatable":
            cols = params.get("columns") or ["Topic", "Key point", "Source"]
            if LLM_PROVIDER == "mock": raise RuntimeError("mock")
            raw = llm_chat_json(f"Return STRICT JSON {{\"columns\": {json.dumps(cols)}, \"rows\": [[\"... value per column ...\"]]}} (max 30 rows)",
                f"Extract a data table with columns {cols} from these passages.\n\n{ctx}")
            content = {"columns": raw.get("columns", cols), "rows": raw.get("rows", [])}
            fp = ARTIFACTS / f"{nbid}_datatable_{uuid.uuid4().hex[:8]}.csv"
            with open(fp, "w", newline="") as f:  # noqa: ASYNC230 - tiny local CSV write, negligible block
                w = csv.writer(f); w.writerow(content["columns"]); w.writerows(content["rows"])
            return save_artifact(nbid, kind, "Data table", params, content, str(fp))
        gen = None if LLM_PROVIDER == "mock" else llm_chat_json
        if kind == "audio":
            script = await media.gen_audio_script(picked, params, gen)
            work = ARTIFACTS / f"work_{uuid.uuid4().hex[:8]}"; work.mkdir(parents=True, exist_ok=True)
            try:
                final, chapters, dur = await media.build_audio(work, script["turns"], params.get("language", "en"), TTS_PROVIDER, lambda f, m: P(0.2 + 0.75 * f, m), params.get("smart_pause", False))
            except Exception as e:
                raise HTTPException(500, f"audio build failed: {e}")
            dest = ARTIFACTS / f"{nbid}_audio_{uuid.uuid4().hex[:8]}{final.suffix}"
            shutil.move(str(final), dest)
            return save_artifact(nbid, kind, f"Audio Overview ({params.get('length', 'standard')})", params,
                                 {"turns": script["turns"], "chapters": chapters, "duration_sec": dur, "focus": script.get("focus", "")}, str(dest))
        if kind == "video":
            slides = await media.gen_video_slides(picked, params, gen)
            work = ARTIFACTS / f"work_{uuid.uuid4().hex[:8]}"; work.mkdir(parents=True, exist_ok=True)
            try:
                final = await media.build_video(work, slides, params.get("language", "en"), TTS_PROVIDER, lambda f, m: P(0.25 + 0.7 * f, m))
            except Exception as e:
                raise HTTPException(500, f"video build failed: {e}")
            dest = ARTIFACTS / f"{nbid}_video_{uuid.uuid4().hex[:8]}.mp4"
            shutil.move(str(final), dest)
            return save_artifact(nbid, kind, "Video Overview", params, {"slides": slides}, str(dest))
        if kind == "slides":
            slides = await media.gen_video_slides(picked, params, gen)
            want = int(params.get("slide_count", 0) or len(slides))
            slides = slides[:max(1, min(want, len(slides)))]
            dest = ARTIFACTS / f"{nbid}_slides_{uuid.uuid4().hex[:8]}.pptx"
            with db() as c:
                nbrow = c.execute("SELECT title FROM notebooks WHERE id=?", (nbid,)).fetchone()
            media.build_pptx(dest, (nbrow["title"] if nbrow else "Notebook") or "Notebook", slides)
            return save_artifact(nbid, kind, "Slide Deck", params, {"slides": slides}, str(dest))
        if kind == "infographic":
            sents = media.sentences_of(picked)
            points = [s for s, _ in sents[:6]] or ["Add more sources for richer visuals."]
            dest = ARTIFACTS / f"{nbid}_infographic_{uuid.uuid4().hex[:8]}.png"
            with db() as c:
                nbrow = c.execute("SELECT title FROM notebooks WHERE id=?", (nbid,)).fetchone()
            media.render_infographic_png(dest, (nbrow["title"] if nbrow else "Overview") or "Overview", points, stats(nbid), params.get("theme", "brand"))
            return save_artifact(nbid, kind, "Infographic", params, {"points": points}, str(dest))
        raise HTTPException(404, f"unknown studio tool: {kind}")
    except HTTPException:
        raise
    except Exception:
        # ---- mock fallbacks (extractive, offline) ----
        if kind == "report":
            md = "## Briefing (offline draft)\n\n" + "\n".join(
                f"- {' '.join(ch['text'].split()[:40])}… [{i+1}]" for i, ch in enumerate(picked[:6]))
            cits = [{"ref": i+1, "source_id": ch["source_id"], "source_title": ch.get("stitle", ""),
                     "chunk_id": ch["id"], "quote": " ".join(ch["text"].split()[:40])} for i, ch in enumerate(picked[:6])]
            return save_artifact(nbid, kind, "Briefing report (offline)", params, {"md": md, "citations": cits})
        if kind == "flashcards":
            n = min(int(params.get("count", 10)), len(picked))
            cards = [{"front": f"What is the key point of passage {i+1} in {picked[i].get('stitle','')}?",
                        "back": " ".join(picked[i]["text"].split()[:60]), "source_id": picked[i]["source_id"]} for i in range(max(n, 1))]
            return save_artifact(nbid, kind, f"Flashcards ×{len(cards)} (offline)", params, {"cards": cards})
        if kind == "quiz":
            qs = [{"q": f"Which source discusses: {' '.join(picked[i]['text'].split()[:12])}…?",
                   "type": "mcq", "choices": [picked[i].get("stitle", "A"), "Unrelated source A", "Unrelated source B", "None of these"],
                   "answer": 0, "explanation": "Answer grounded in the cited source.", "source_id": picked[i]["source_id"]}
                  for i in range(min(int(params.get("count", 5)), len(picked)) or 1)]
            return save_artifact(nbid, kind, f"Quiz ×{len(qs)} (offline)", params, {"questions": qs})
        if kind == "mindmap":
            nodes = [{"id": f"n{i}", "label": (ch.get("stitle", "")[:28] or f"Topic {i+1}"), "children": []} for i, ch in enumerate(picked[:8])]
            return save_artifact(nbid, kind, "Mind map (offline)", params,
                                 {"root": "Sources overview", "nodes": [{"id": "root", "label": "Sources overview", "children": [n["id"] for n in nodes]}] + nodes})
        if kind == "datatable":
            cols = params.get("columns") or ["Topic", "Key point", "Source"]
            rows = [[ch.get("stitle", "")[:30], " ".join(ch["text"].split()[:15]), ch.get("stitle", "")[:20]] for ch in picked[:10]]
            fp = ARTIFACTS / f"{nbid}_datatable_{uuid.uuid4().hex[:8]}.csv"
            with open(fp, "w", newline="") as f:  # noqa: ASYNC230 - tiny local CSV write, negligible block
                w = csv.writer(f); w.writerow(cols); w.writerows(rows)
            return save_artifact(nbid, kind, "Data table (offline)", params, {"columns": cols, "rows": rows}, str(fp))
        raise


@app.post("/api/notebooks/{nbid}/studio/{kind}")
async def studio(nbid: str, kind: str, req: Request, bg: int = 0):
    get_nb(nbid)
    check_quota("global", "studio", LIM_STUDIO)
    params = await req.json() if req.headers.get("content-length", "0") != "0" else {}
    if isinstance(params, list): params = {}
    if bg:
        return run_bg(f"studio:{kind}", nbid, lambda prog: studio_impl(nbid, kind, params, prog))
    return await studio_impl(nbid, kind, params)

@app.get("/api/notebooks/{nbid}/studio")
def list_art(nbid: str):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM artifacts WHERE notebook_id=? ORDER BY created_at DESC", (nbid,)).fetchall()]

@app.get("/api/artifacts/{aid}")
def get_art(aid: str):
    with db() as c:
        a = row2dict(c.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone())
        if not a: raise HTTPException(404, "artifact not found")
        a["content"] = json.loads(a["content_json"] or "{}"); a["params"] = json.loads(a["params_json"] or "{}")
        return a

@app.get("/api/artifacts/{aid}/download")
def dl_art(aid: str, inline: int = 0):
    with db() as c:
        a = row2dict(c.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone())
        if not a or not a["file_path"] or not Path(a["file_path"]).exists(): raise HTTPException(404, "no file")
        if inline:
            mt, _ = mimetypes.guess_type(a["file_path"])
            return FileResponse(a["file_path"], media_type=mt or "application/octet-stream",
                                headers={"Content-Disposition": "inline"})
        return FileResponse(a["file_path"], filename=Path(a["file_path"]).name)

# ---------------- API: research (Deep/Fast) ----------------
def ddg_search(query: str, n=5):
    """Multi-engine web search: DDG html -> DDG lite -> Wikipedia opensearch."""
    import urllib.parse
    urls = []
    # 1) DDG html endpoint
    try:
        r = httpx.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                if "uddg=" in href:
                    urls.append(urllib.parse.unquote(href.split("uddg=", 1)[1].split("&")[0]))
                elif href.startswith("http"):
                    urls.append(href)
                if len(urls) >= n:
                    return urls
    except Exception:
        pass
    # 2) DDG lite endpoint (direct links)
    try:
        r = httpx.get("https://lite.duckduckgo.com/lite/", params={"q": query}, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href*=uddg=]"):
                href = a.get("href", "")
                try:
                    u = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&")[0])
                except Exception:
                    continue
                if u.startswith("http") and u not in urls:
                    urls.append(u)
                if len(urls) >= n:
                    return urls
            for a in soup.select("a[href^=http]"):
                href = a.get("href", "")
                if "duckduckgo.com" in href or not a.get_text(strip=True):
                    continue
                if href not in urls:
                    urls.append(href)
                if len(urls) >= n:
                    return urls
    except Exception:
        pass
    # 3) Wikipedia full-text search (JSON, very reliable)
    try:
        r = httpx.get("https://en.wikipedia.org/w/api.php",
                      params={"action": "query", "list": "search", "srsearch": query,
                              "srlimit": n, "format": "json"},
                      timeout=20, headers={"User-Agent": "NotebookLM-Clone/1.0"})
        if r.status_code == 200:
            for hit in r.json().get("query", {}).get("search", [])[:n]:
                u = "https://en.wikipedia.org/wiki/" + hit["title"].replace(" ", "_")
                if u not in urls:
                    urls.append(u)
            if len(urls) >= n:
                return urls[:n]
    except Exception:
        pass
    # 4) Wikipedia opensearch (title match)
    try:
        r = httpx.get("https://en.wikipedia.org/w/api.php",
                      params={"action": "opensearch", "search": query, "limit": n, "format": "json"},
                      timeout=20, headers={"User-Agent": "NotebookLM-Clone/1.0"})
        if r.status_code == 200:
            for u in r.json()[3][:n]:
                if u not in urls:
                    urls.append(u)
    except Exception:
        pass
    return urls[:n]

async def research_impl(nbid: str, query: str, depth: str, prog=None):
    def P(f, m):
        if prog:
            prog(f, m)
    P(0.05, "searching the web")
    try:
        urls = ddg_search(query, 12 if depth == "deep" else 5)
    except Exception as e:
        raise HTTPException(502, f"web search failed: {e}")
    added, errors = [], []
    for u in urls:
        try:
            if not u.startswith("http"):
                continue
            text = fetch_url(u)
            if len(text.split()) < 40:
                continue
            s = add_source_text(nbid, "url", (u[:70] + " \U0001f50e"), u, text)
            added.append({"id": s["id"], "title": s["title"]})
            P(0.1 + 0.7 * len(added) / max(1, min(len(urls), 10)), f"imported {len(added)} sources")
        except Exception as e:
            errors.append(f"{u[:60]}: {str(e)[:80]}")
        if len(added) >= (10 if depth == "deep" else 4):
            break
    report = None
    if added:
        try:
            picked, ctx = studio_context(nbid)
            if LLM_PROVIDER == "mock":
                md = "## Research briefing: " + query + "\n\n" + "\n".join(
                    f"- {' '.join(ch['text'].split()[:40])}\u2026 [{i+1}]" for i, ch in enumerate(picked[:6]))
                cits = [{"ref": i + 1, "source_id": ch["source_id"], "source_title": ch.get("stitle", ""),
                         "chunk_id": ch["id"], "quote": " ".join(ch["text"].split()[:40])} for i, ch in enumerate(picked[:6])]
            else:
                raw = llm_chat_json("Return STRICT JSON {\"md\": \"...\", \"citations\": [...]}",
                                    f"Write a research briefing answering: {query}\n\n{ctx}")
                md, cits = raw.get("md", ""), verify_citations(raw.get("citations", []), picked)
            report = save_artifact(nbid, "report", f"Research: {query[:50]}",
                                   {"type": "briefing", "query": query}, {"md": md, "citations": cits})
        except Exception as e:
            errors.append(f"report: {e}")
    return {"added": added, "report_id": report["id"] if report else None, "errors": errors}


@app.post("/api/notebooks/{nbid}/research")
async def research(nbid: str, req: Request, bg: int = 0):
    get_nb(nbid)
    check_quota("global", "research", LIM_RESEARCH)
    b = await req.json()
    query = (b.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Empty query")
    depth = b.get("depth", "fast")
    if bg:
        return run_bg("research", nbid, lambda prog: research_impl(nbid, query, depth, prog))
    return await research_impl(nbid, query, depth)


@app.post("/api/quotas:reset")
def quotas_reset():
    day = datetime.date.today().isoformat()  # noqa: DTZ011 - quotas key on local calendar day by design
    with db() as c:
        c.execute("DELETE FROM usage WHERE day=?", (day,))
    return {"reset": day, "message": "daily quotas cleared"}


@app.get("/api/quotas")
def quotas():
    day = datetime.date.today().isoformat()  # noqa: DTZ011 - quotas key on local calendar day by design
    with db() as c:
        rows = c.execute("SELECT counter, SUM(n) n FROM usage WHERE day=? GROUP BY counter", (day,)).fetchall()
    used = {r["counter"]: r["n"] for r in rows}
    return {"day": day, "chats": {"used": used.get("chats", 0), "limit": LIM_CHATS},
            "studio": {"used": used.get("studio", 0), "limit": LIM_STUDIO},
            "research": {"used": used.get("research", 0), "limit": LIM_RESEARCH}}

# ---------------- shares (simple public token links) ----------------
@app.post("/api/notebooks/{nbid}/shares")
async def mk_share(nbid: str, req: Request):
    b = await req.json() if req.headers.get("content-length", "0") != "0" else {}
    tok = uuid.uuid4().hex[:10]
    with db() as c:
        c.execute("INSERT INTO shares(id,notebook_id,kind,token,artifact_id,created_at) VALUES(?,?,?,?,?,?)",
                  (nid("sh_"), nbid, b.get("kind", "notebook"), tok, b.get("artifact_id"), now()))
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or ""
    return {"token": tok, "url": f"{base}/s/{tok}"}

@app.get("/api/shares/{token}")
def share_json(token: str):
    with db() as c:
        s = row2dict(c.execute("SELECT * FROM shares WHERE token=?", (token,)).fetchone())
        if not s:
            raise HTTPException(404, "share not found")
        nb = row2dict(c.execute("SELECT * FROM notebooks WHERE id=?", (s["notebook_id"],)).fetchone())
        arts = [dict(r) for r in c.execute("SELECT id,kind,title,created_at FROM artifacts WHERE notebook_id=?", (s["notebook_id"],)).fetchall()]
        return {"notebook": {"id": nb["id"], "title": nb["title"]}, "artifacts": arts}

@app.get("/s/{token}")
def view_share(token: str):
    from fastapi.responses import HTMLResponse
    d = share_json(token)
    items = "".join(f"<li><b>{a['kind']}</b> \u2014 {a['title']} <small>{(a['created_at'] or '')[:10]}</small></li>" for a in d["artifacts"]) or "<li>No artifacts yet.</li>"
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><title>Shared notebook</title></head>"
        f"<body style='font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px'>"
        f"<h2>\U0001f4d3 {d['notebook']['title']}</h2><p style='color:#666'>Shared read-only \u00b7 NotebookLM Clone</p><ul>{items}</ul></body></html>")

# ---------------- frontend ----------------
FRONT = BASE / "static"
FRONT.mkdir(exist_ok=True)
if (FRONT / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONT), html=True), name="static")
else:
    @app.get("/")
    def root():
        return {"name": "NotebookLM Clone API", "docs": "/docs", "health": "/api/health",
                "note": "frontend not built yet — add backend/app/static/index.html"}
