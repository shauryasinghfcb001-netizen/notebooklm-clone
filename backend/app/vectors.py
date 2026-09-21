"""Vector retrieval: dense MiniLM embeddings (SQLite blobs, per-notebook namespace)
with TF-IDF fallback. Backend via EMBEDDINGS=auto|dense|tfidf (default auto).

Auto mode uses dense embeddings when the stack is importable AND the model
loads; otherwise it silently falls back to TF-IDF so the app always works.
"""
from __future__ import annotations

import os
import sqlite3
import struct

BACKEND_WANT = os.environ.get("EMBEDDINGS", "auto").lower()
EMBED_MODEL = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")
_model = None
_tried = False


def dense_available() -> bool:
    global _model, _tried
    if _model is not None:
        return True
    if _tried:
        return False
    _tried = True
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
        _model.max_seq_length = 256
        return True
    except Exception as e:
        print("dense embeddings unavailable:", str(e)[:200])
        return False


def active_backend() -> str:
    if BACKEND_WANT == "tfidf":
        return "tfidf"
    return "dense" if dense_available() else "tfidf"


def status() -> dict:
    return {"want": BACKEND_WANT, "model": EMBED_MODEL, "dense_loaded": _model is not None, "rerank": {"want": RERANK_WANT, "loaded": _ce is not None}}


def _conn(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS embeddings(chunk_id TEXT PRIMARY KEY, notebook_id TEXT, source_id TEXT, dim INTEGER, vec BLOB)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_emb_nb ON embeddings(notebook_id)")
    return c


def upsert(db_path, notebook_id, rows) -> int:
    """rows: [(chunk_id, source_id, text)]. No-op on tfidf; raises if dense wanted but broken."""
    if BACKEND_WANT == "tfidf":
        return 0
    if not dense_available():
        raise RuntimeError("dense backend unavailable")
    texts = [(t or "")[:2000] for _, _, t in rows]
    vecs = _model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    dim = int(vecs.shape[1])
    with _conn(db_path) as c:
        c.executemany(
            "INSERT OR REPLACE INTO embeddings(chunk_id,notebook_id,source_id,dim,vec) VALUES(?,?,?,?,?)",
            [(cid, notebook_id, sid, dim, struct.pack(f"{dim}f", *map(float, v))) for (cid, sid, _), v in zip(rows, vecs)],
        )
    return len(rows)


def delete_source(db_path, notebook_id, source_id):
    with _conn(db_path) as c:
        c.execute("DELETE FROM embeddings WHERE notebook_id=? AND source_id=?", (notebook_id, source_id))


def delete_notebook(db_path, notebook_id):
    with _conn(db_path) as c:
        c.execute("DELETE FROM embeddings WHERE notebook_id=?", (notebook_id,))


def _diverse(ranked, k, per_src=3):
    out, seen = [], {}
    for score, ch in ranked:
        if seen.get(ch["source_id"], 0) >= per_src:
            continue
        seen[ch["source_id"]] = seen.get(ch["source_id"], 0) + 1
        out.append({**ch, "score": float(score)})
        if len(out) >= k:
            break
    return out


def search_tfidf(chunks, query, k):
    if len(chunks) == 1:
        return [{**chunks[0], "score": 1.0}]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(max_features=5000, stop_words="english").fit([c["text"] for c in chunks] + [query])
        M = vec.transform([c["text"] for c in chunks])
        q = vec.transform([query])
        sims = cosine_similarity(q, M)[0]
        ranked = sorted(zip(sims, chunks), key=lambda x: -x[0])
        out = _diverse(ranked, k)
        return [o for o in out if o["score"] > 0.01] or out[:2]
    except Exception:
        qws = set(query.lower().split())

        def sc(t):
            ws = t.lower().split()
            return sum(1 for w in qws if w in ws)

        return sorted([{**c, "score": sc(c["text"])} for c in chunks], key=lambda x: -x["score"])[:k]


def search_dense(db_path, chunks, notebook_id, query, k):
    import numpy as np
    qv = _model.encode([query[:2000]], normalize_embeddings=True, show_progress_bar=False)[0]
    with _conn(db_path) as c:
        rows = c.execute("SELECT chunk_id, dim, vec FROM embeddings WHERE notebook_id=?", (notebook_id,)).fetchall()
    if not rows:
        raise RuntimeError("no embeddings yet")
    by_id = {r[0]: (r[1], r[2]) for r in rows}
    scored = []
    for ch in chunks:
        hit = by_id.get(ch["id"])
        if not hit:
            continue
        dim, blob = hit
        v = np.array(struct.unpack(f"{dim}f", blob))
        scored.append((float(np.dot(qv, v)), ch))
    if not scored:
        raise RuntimeError("no overlapping embeddings")
    scored.sort(key=lambda x: -x[0])
    out = _diverse(scored, k)
    return [o for o in out if o["score"] > 0.05] or out[:2]


RERANK_WANT = os.environ.get("RERANK", "auto").lower()
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_ce = None


def ce_available():
    global _ce
    if RERANK_WANT == "off":
        return False
    if _ce is not None:
        return True
    try:
        from sentence_transformers import CrossEncoder
        _ce = CrossEncoder(RERANK_MODEL)
        return True
    except Exception as e:
        print("reranker unavailable:", str(e)[:150])
        return False


def rerank(query, cands, top_k):
    """Cross-encoder rerank of stage-1 candidates. Reorder-only: never changes the refuse gate."""
    if not cands or len(cands) <= 1 or RERANK_WANT == "off":
        return list(cands)[:top_k]
    try:
        if not ce_available():
            return list(cands)[:top_k]
        pairs = [(query[:500], c["text"][:500]) for c in cands]
        scores = _ce.predict(pairs, show_progress_bar=False)
        ranked = sorted(zip(scores, cands), key=lambda x: -float(x[0]))
        return [{**c, "score": float(s)} for s, c in ranked[:top_k]]
    except Exception as e:
        print("rerank failed:", str(e)[:150])
        return list(cands)[:top_k]


def search(db_path, chunks, notebook_id, query, k=8):
    if not chunks:
        return []
    k2 = min(max(k * 2, k), 12)
    if BACKEND_WANT != "tfidf" and dense_available():
        try:
            return rerank(query, search_dense(db_path, chunks, notebook_id, query, k2), k)
        except Exception as e:
            print("dense search failed, tfidf fallback:", str(e)[:150])
    return rerank(query, search_tfidf(chunks, query, k2), k)
