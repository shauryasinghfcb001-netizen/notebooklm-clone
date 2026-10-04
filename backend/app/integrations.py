"""Google Drive import + Sheets export via OAuth web flow.

Graceful when unconfigured: every entry raises NotConfigured with a setup message
instead of crashing, so the UI can show "connect Google" hints. Tokens are
workspace-level (one Drive connection shared by the team).
"""
from __future__ import annotations

import json
import os

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

EXPORT_MAP = {
    "application/vnd.google-apps.document": ("txt", "text/plain"),
    "application/vnd.google-apps.spreadsheet": ("csv", "text/csv"),
    "application/vnd.google-apps.presentation": ("txt", "text/plain"),
}

SETUP_MSG = ("Google not connected. Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET "
             "(Google Cloud Console → APIs & Services → Credentials → OAuth client, "
             "authorized redirect {origin}/api/integrations/drive/callback), restart, "
             "then open the Drive auth URL.")

SCHEMA = "CREATE TABLE IF NOT EXISTS integrations(provider TEXT PRIMARY KEY, token_json TEXT, updated_at TEXT);\n"


class NotConfigured(Exception):
    pass


def init_integrations(c):
    c.executescript(SCHEMA)


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def capability_catalog() -> list[dict]:
    """Integration contract for features that are intentionally not enabled yet."""
    return [
        {"id": "google-drive", "provider": "Google", "status": "ready" if configured() else "setup_required", "purpose": "Import Drive files and export data tables to Sheets", "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]},
        {"id": "google-ai", "provider": "Google AI / Vertex AI", "status": "planned", "purpose": "Optional generation provider for the Understanding Agent", "env": ["GOOGLE_API_KEY or VERTEX_*"], "not_active": True},
        {"id": "speech", "provider": "Google Cloud Speech-to-Text", "status": "planned", "purpose": "Future voice input; no microphone capture is implemented", "env": ["GOOGLE_APPLICATION_CREDENTIALS"], "not_active": True},
        {"id": "video-generation", "provider": "Google Veo / compatible provider", "status": "planned", "purpose": "Future generated-video provider; current video is locally rendered", "env": ["VIDEO_GENERATION_API_KEY"], "not_active": True},
    ]


def _libs():
    try:
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        return Flow, build
    except ImportError as e:
        raise NotConfigured("Google libs missing: pip install google-api-python-client google-auth-oauthlib") from e


def _client_config():
    return {"web": {"client_id": os.environ["GOOGLE_CLIENT_ID"],
                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"}}


def auth_url(redirect_uri: str, origin: str) -> str:
    if not configured():
        raise NotConfigured(SETUP_MSG.format(origin=origin))
    Flow, _ = _libs()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent",
                                    include_granted_scopes="true")
    return url


def exchange(code: str, redirect_uri: str) -> dict:
    if not configured():
        raise NotConfigured("GOOGLE_CLIENT_ID/SECRET not set")
    Flow, _ = _libs()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    return json.loads(flow.credentials.to_json())


def save_token(c, token: dict):
    import datetime
    c.execute("INSERT INTO integrations(provider,token_json,updated_at) VALUES('google',?,?) "
              "ON CONFLICT(provider) DO UPDATE SET token_json=excluded.token_json, updated_at=excluded.updated_at",
              (json.dumps(token), datetime.datetime.now(datetime.UTC).isoformat()))


def load_token(c) -> dict | None:
    r = c.execute("SELECT token_json FROM integrations WHERE provider='google'").fetchone()
    return json.loads(r["token_json"]) if r else None


def _service(c, api: str, version: str, origin: str):
    tok = load_token(c)
    if not tok:
        raise NotConfigured("Drive not connected yet — open the Drive auth URL first. " +
                            SETUP_MSG.format(origin=origin) if not configured() else
                            "Drive not connected yet — open the Drive auth URL first.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        _, build = _libs()
        creds = Credentials(tok.get("token"), refresh_token=tok.get("refresh_token"),
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
                            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"), scopes=SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_token(c, json.loads(creds.to_json()))
        return build(api, version, credentials=creds)
    except NotConfigured:
        raise
    except Exception as e:
        raise NotConfigured(f"Google auth failed ({str(e)[:120]}). Reconnect via the Drive auth URL.") from e


def drive_files(c, origin: str, q: str = "") -> list:
    svc = _service(c, "drive", "v3", origin)
    query = q or "trashed=false"
    res = svc.files().list(q=query, pageSize=50, fields="files(id,name,mimeType,modifiedTime)",
                           orderBy="modifiedTime desc").execute()
    return res.get("files", [])


def drive_fetch(c, origin: str, file_id: str) -> tuple[str, str, bytes | str]:
    """Returns (filename, kind, payload): kind 'text' -> str, 'bytes' -> raw bytes."""
    svc = _service(c, "drive", "v3", origin)
    meta = svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    name, mime = meta.get("name", file_id), meta.get("mimeType", "")
    if mime in EXPORT_MAP:
        suffix, exp_mime = EXPORT_MAP[mime]
        data = svc.files().export(fileId=file_id, mimeType=exp_mime).execute()
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        return f"{name}.{suffix}", "text", text
    if mime.startswith("text/") or mime in ("application/json", "application/xml", "text/markdown"):
        data = svc.files().get_media(fileId=file_id).execute()
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        return name, "text", text
    data = svc.files().get_media(fileId=file_id).execute()
    return name, "bytes", bytes(data)


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "A"


def sheets_push(c, origin: str, title: str, columns: list, rows: list) -> str:
    svc = _service(c, "sheets", "v4", origin)
    sheet = svc.spreadsheets().create(body={"properties": {"title": title or "NotebookLM export"}}).execute()
    sid = sheet["spreadsheetId"]
    values = [list(columns or [])] + [list(r) for r in (rows or [])]
    if values:
        rng = f"Sheet1!A1:{_col_letter(max(1, len(values[0])))}{len(values)}"
        svc.spreadsheets().values().update(spreadsheetId=sid, range=rng,
                                           valueInputOption="RAW", body={"values": values}).execute()
    return sheet.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sid}")
