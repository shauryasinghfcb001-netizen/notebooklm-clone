"""Optional team auth: pbkdf2 users + SQLite sessions + notebook members + analytics.

AUTH_REQUIRED=0 (default): all guards pass through as the local owner (v1 behavior,
byte-identical). AUTH_REQUIRED=1: /api/* needs a session except public paths.
First registered user becomes admin. Drive/Google tokens stay workspace-level.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import secrets

AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "0") == "1"
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
COOKIE = "nb_session"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT, role TEXT DEFAULT 'member', created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT, expires_at TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS members(notebook_id TEXT, user_id TEXT, role TEXT DEFAULT 'viewer', PRIMARY KEY(notebook_id, user_id));
CREATE TABLE IF NOT EXISTS usage_log(day TEXT, who TEXT, counter TEXT, n INTEGER, PRIMARY KEY(day, who, counter));
"""


def init_auth(c):
    c.executescript(SCHEMA)
    cols = [r[1] for r in c.execute("PRAGMA table_info(notebooks)")]
    if "owner_id" not in cols:
        c.execute("ALTER TABLE notebooks ADD COLUMN owner_id TEXT")


def _now():
    return datetime.datetime.now(datetime.UTC)


def hash_pw(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
    return f"{salt}${h.hex()}"


def check_pw(password: str, stored: str) -> bool:
    try:
        salt, hexh = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
        return hmac.compare_digest(h.hex(), hexh)
    except Exception:
        return False


def register(c, username: str, password: str) -> dict:
    username = (username or "").strip()
    if not username or len(password or "") < 4:
        raise ValueError("username required, password min 4 chars")
    uid = "u_" + secrets.token_hex(6)
    n = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    role = "admin" if n == 0 else "member"
    try:
        c.execute("INSERT INTO users(id,username,pw_hash,role,created_at) VALUES(?,?,?,?,?)",
                  (uid, username, hash_pw(password), role, _now().isoformat()))
    except Exception:
        raise ValueError("username taken") from None
    return {"id": uid, "username": username, "role": role}


def login(c, username: str, password: str) -> str | None:
    r = c.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if not r or not check_pw(password or "", r["pw_hash"]):
        return None
    tok = secrets.token_urlsafe(32)
    exp = (_now() + datetime.timedelta(days=SESSION_DAYS)).isoformat()
    c.execute("INSERT INTO sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",
              (tok, r["id"], exp, _now().isoformat()))
    return tok


def logout(c, token: str):
    c.execute("DELETE FROM sessions WHERE token=?", (token,))


def user_from_token(c, token: str) -> dict | None:
    r = c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=?",
                  (token,)).fetchone()
    if not r:
        return None
    exp = c.execute("SELECT expires_at FROM sessions WHERE token=?", (token,)).fetchone()
    if not exp or exp["expires_at"] < _now().isoformat():
        c.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    return {"id": r["id"], "username": r["username"], "role": r["role"]}


def member_role(c, notebook_id: str, user_id: str) -> str | None:
    nb = c.execute("SELECT owner_id FROM notebooks WHERE id=?", (notebook_id,)).fetchone()
    if not nb:
        return None
    if nb["owner_id"] == user_id:
        return "owner"
    r = c.execute("SELECT role FROM members WHERE notebook_id=? AND user_id=?",
                  (notebook_id, user_id)).fetchone()
    return r["role"] if r else None


_LEVELS = {"viewer": 1, "editor": 2, "owner": 3}


def require_level(role: str | None, level: str, open_when_legacy: bool) -> bool:
    """True if role satisfies level. Legacy notebooks (no owner/members) are open."""
    if role is None:
        return open_when_legacy
    need = {"read": 1, "write": 2, "admin": 3}[level]
    return _LEVELS.get(role, 0) >= need


def log_usage(c, who: str, counter: str):
    day = datetime.date.today().isoformat()  # noqa: DTZ011 - analytics keyed on local calendar day by design
    c.execute("INSERT INTO usage_log(day,who,counter,n) VALUES(?,?,?,1) "
              "ON CONFLICT(day,who,counter) DO UPDATE SET n=n+1", (day, who, counter))


def analytics(c, days: int = 14):
    rows = c.execute("SELECT day,who,counter,SUM(n) n FROM usage_log GROUP BY day,who,counter "
                     "ORDER BY day DESC LIMIT 5000").fetchall()
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["day"], r["who"])
        d = out.setdefault(key, {"day": r["day"], "who": r["who"], "chats": 0, "studio": 0, "research": 0})
        if r["counter"] in d:
            d[r["counter"]] = r["n"]
    return sorted(out.values(), key=lambda x: (x["day"], x["who"]), reverse=True)[:days * 50]
