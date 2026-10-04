"""Core + Studio test suite (runs fully offline with mock LLM)."""
import os
import tempfile

tmp = tempfile.mkdtemp(prefix="nbtest_")
os.environ["STORAGE_DIR"] = tmp
os.environ["LLM_PROVIDER"] = "mock"
os.environ["TTS_PROVIDER"] = "mock"  # offline beeps, no network stalls

import pytest
from app.main import app
from fastapi.testclient import TestClient

c = TestClient(app)
NB = None


def test_health():
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]


def test_notebook_crud():
    global NB
    r = c.post("/api/notebooks", json={"title": "Test NB"})
    assert r.status_code == 200
    NB = r.json()["id"]
    assert c.get(f"/api/notebooks/{NB}").status_code == 200
    assert c.patch(f"/api/notebooks/{NB}", json={"title": "Renamed"}).json()["title"] == "Renamed"


def test_ingest_and_grounded_chat():
    c.post(f"/api/notebooks/{NB}/sources:paste",
           json={"title": "Cats", "text": "Cats are small carnivorous mammals. Cats sleep up to sixteen hours per day. A group of cats is called a clowder."})
    c.post(f"/api/notebooks/{NB}/sources:paste",
           json={"title": "Dogs", "text": "Dogs are loyal domesticated mammals. Dogs were domesticated from wolves. A group of dogs is called a pack."})
    srcs = c.get(f"/api/notebooks/{NB}/sources").json()
    assert len(srcs) == 2
    r = c.post(f"/api/notebooks/{NB}/chat", json={"message": "How long do cats sleep per day?"})
    d = r.json()
    assert "sixteen" in d["answer_md"], d
    assert len(d["citations"]) >= 1
    assert d["citations"][0]["source_title"] == "Cats"
    # disabling the key source must change the answer
    cat_id = next(s["id"] for s in srcs if s["title"] == "Cats")
    c.patch(f"/api/notebooks/{NB}/sources/{cat_id}", json={"enabled": False})
    r2 = c.post(f"/api/notebooks/{NB}/chat", json={"message": "How long do cats sleep per day?"})
    assert "sixteen" not in r2.json()["answer_md"]
    c.patch(f"/api/notebooks/{NB}/sources/{cat_id}", json={"enabled": True})


def test_notes_roundtrip():
    hist = c.get(f"/api/notebooks/{NB}/chat").json()
    aid = next(m["id"] for m in hist if m["role"] == "assistant")
    n = c.post(f"/api/notebooks/{NB}/notes:from-chat", json={"chat_id": aid}).json()
    assert "sixteen" in n["content_md"]
    assert len(c.get(f"/api/notebooks/{NB}/notes").json()) >= 1


def test_studio_text_tools():
    for kind, params in [("report", {"type": "briefing"}), ("flashcards", {"count": 4}),
                         ("quiz", {"count": 2}), ("mindmap", {}),
                         ("datatable", {"columns": ["Topic", "Fact"]})]:
        r = c.post(f"/api/notebooks/{NB}/studio/{kind}", json=params)
        assert r.status_code == 200, (kind, r.text[:200])
        a = c.get(f"/api/artifacts/{r.json()['id']}").json()
        assert a["content"], kind
    # CSV download works
    arts = c.get(f"/api/notebooks/{NB}/studio").json()
    dt = next(a for a in arts if a["kind"] == "datatable")
    dl = c.get(f"/api/artifacts/{dt['id']}/download")
    assert dl.status_code == 200 and b"Topic" in dl.content


def test_studio_media_files():
    import glob
    for kind, params in [("slides", {"slide_count": 3}), ("infographic", {}),
                         ("audio", {"length": "brief"}), ("video", {})]:
        r = c.post(f"/api/notebooks/{NB}/studio/{kind}", json=params)
        assert r.status_code == 200, (kind, r.text[:300])
        fp = r.json()["file_path"]
        assert fp and os.path.exists(fp), (kind, fp)
    assert glob.glob(os.path.join(tmp, "artifacts", "*_slides_*.pptx"))
    assert glob.glob(os.path.join(tmp, "artifacts", "*_infographic_*.png"))
    assert glob.glob(os.path.join(tmp, "artifacts", "*_audio_*.*"))
    assert glob.glob(os.path.join(tmp, "artifacts", "*_video_*.mp4"))


def test_quotas_and_share():
    q = c.get("/api/quotas").json()
    assert q["chats"]["used"] >= 2 and q["studio"]["used"] >= 9
    tok = c.post(f"/api/notebooks/{NB}/shares", json={"kind": "notebook"}).json()["token"]
    assert c.get(f"/s/{tok}").status_code == 200
    assert c.get(f"/api/shares/{tok}").json()["notebook"]["id"] == NB


def test_duplicate_and_note_context():
    r = c.post(f"/api/notebooks/{NB}/duplicate")
    assert r.status_code == 200
    nb2 = r.json()["id"]
    assert len(c.get(f"/api/notebooks/{nb2}/sources").json()) == 2
    c.delete(f"/api/notebooks/{nb2}")
    n = c.post(f"/api/notebooks/{NB}/notes", json={"title": "Ctx", "content_md": "Zebras have distinctive black and white stripes."}).json()
    d = c.post(f"/api/notebooks/{NB}/chat", json={"message": "What stripes do zebras have?", "note_ids": [n["id"]]}).json()
    assert "Zebras" in d["answer_md"], d


def test_report_pdf_export():
    arts = c.get(f"/api/notebooks/{NB}/studio").json()
    rep = next(a for a in arts if a["kind"] == "report")
    assert rep["file_path"] and rep["file_path"].endswith(".pdf")
    assert os.path.exists(rep["file_path"])
    dl = c.get(f"/api/artifacts/{rep['id']}/download")
    assert dl.status_code == 200 and dl.content[:4] == b"%PDF"


def test_bg_job_flow():
    import time
    r = c.post(f"/api/notebooks/{NB}/studio/report?bg=1", json={"type": "briefing"})
    assert r.status_code == 200 and "job_id" in r.json()
    jid = r.json()["job_id"]
    for _ in range(60):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    assert j["result"]["artifact_id"]
    assert c.get(f"/api/artifacts/{j['result']['artifact_id']}").status_code == 200


def test_dense_vectors_optional():
    pytest.importorskip("sentence_transformers")
    from app import vectors
    if not vectors.dense_available():
        pytest.skip("model unavailable")
    dbp = os.path.join(tmp, "vec.db")
    vectors.upsert(dbp, "nb1", [("c1", "s1", "Cats sleep sixteen hours per day"),
                                ("c2", "s1", "Dogs were domesticated from wolves")])
    chunks = [{"id": "c1", "source_id": "s1", "stitle": "T", "text": "Cats sleep sixteen hours per day"},
              {"id": "c2", "source_id": "s1", "stitle": "T", "text": "Dogs were domesticated from wolves"}]
    ranked = vectors.search(dbp, chunks, "nb1", "how long do cats sleep", 2)
    assert ranked and ranked[0]["id"] == "c1"


# ---------- v2: teams + google + seed ----------
def test_auth_register_login():
    r = c.post("/api/auth/register", json={"username": "t_alice", "password": "pw1234"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "t_alice"
    assert r.json()["role"] in ("admin", "member")
    r2 = c.post("/api/auth/login", json={"username": "t_alice", "password": "pw1234"})
    assert r2.status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_auth_wrong_pw():
    assert c.post("/api/auth/login", json={"username": "t_alice", "password": "bad"}).status_code == 401
    assert c.post("/api/auth/register", json={"username": "t_alice", "password": "pw1234"}).status_code == 400


def test_auth_guard_on(monkeypatch):
    from app import auth as authmod
    from app.main import app as app2
    from fastapi.testclient import TestClient
    monkeypatch.setattr(authmod, "AUTH_REQUIRED", True)
    t = TestClient(app2)
    assert t.get("/api/notebooks").status_code == 401
    assert t.get("/api/health").status_code == 200
    rr = t.post("/api/auth/register", json={"username": "t_bob", "password": "pw1234"})
    assert rr.status_code == 200
    assert t.get("/api/notebooks").status_code == 200
    nb = t.post("/api/notebooks", json={"title": "Bob nb"}).json()
    assert t.get("/api/notebooks").json()[0]["id"] == nb["id"]
    assert t.get("/api/analytics").status_code == 200
    t.post("/api/auth/logout")
    assert t.get("/api/notebooks").status_code == 401


def test_members_flow():
    nb = c.post("/api/notebooks", json={"title": "Members nb"}).json()
    r = c.post(f"/api/notebooks/{nb['id']}/members", json={"username": "t_alice", "role": "editor"})
    assert r.status_code == 200
    ms = c.get(f"/api/notebooks/{nb['id']}/members").json()
    assert any(m["username"] == "t_alice" for m in ms)
    assert c.post(f"/api/notebooks/{nb['id']}/members", json={"username": "ghost", "role": "viewer"}).status_code == 404
    c.delete(f"/api/notebooks/{nb['id']}")


def test_integrations_status():
    r = c.get("/api/integrations/status").json()
    assert "google_configured" in r and "redirect_uri" in r
    assert r["redirect_uri"].endswith("/api/integrations/drive/callback")
    assert {x["id"] for x in r["capabilities"]} >= {"google-ai", "speech", "video-generation"}


def test_understanding_agent_grounded_route():
    r = c.post(f"/api/notebooks/{NB}/understanding", json={"goal": "Explain this simply to a beginner"})
    assert r.status_code == 200, r.text
    brief = r.json()
    assert brief["audience_level"] == "beginner"
    assert brief["recommended_format"] == "plain-language guide"
    assert len(brief["learning_path"]) == 3
    assert brief["grounding"] and brief["provider"] == "local-planner"


def test_drive_gated(monkeypatch):
    from app import integrations as intmod
    monkeypatch.setattr(intmod, "configured", lambda: False)
    r = c.get("/api/integrations/drive/auth-url")
    assert r.status_code == 400 and "GOOGLE_CLIENT_ID" in r.text
    r2 = c.get("/api/integrations/drive/files")
    assert r2.status_code == 400


def test_demo_seed():
    r = c.post("/api/demo:seed")
    assert r.status_code == 200
    nbid = r.json()["id"]
    assert r.json()["sources"] == 3
    srcs = c.get(f"/api/notebooks/{nbid}/sources").json()
    assert len(srcs) == 3
    c.delete(f"/api/notebooks/{nbid}")


def test_analytics_shape():
    r = c.get("/api/analytics")
    assert r.status_code == 200 and isinstance(r.json(), list)
