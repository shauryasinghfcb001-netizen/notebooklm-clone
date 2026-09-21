"""Citation accuracy eval: seeds 3 sources, asks 6 questions, scores grounding.

Run: cd backend && python eval.py
"""
import os
import tempfile

tmp = tempfile.mkdtemp(prefix="nbeval_")
os.environ["STORAGE_DIR"] = tmp
os.environ["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER", "mock")

from app.main import app
from fastapi.testclient import TestClient
from rapidfuzz import fuzz

c = TestClient(app)

SOURCES = [
    ("Paris", "Paris is the capital of France. The Eiffel Tower in Paris was completed in 1889. Paris sits on the River Seine."),
    ("Tokyo", "Tokyo is the capital of Japan. Tokyo hosted the Summer Olympics in 2021. Tokyo is the largest metropolitan economy in the world."),
    ("Cairo", "Cairo is the capital of Egypt. The Great Pyramid of Giza stands near Cairo. Cairo is the largest city in Africa."),
]
QUESTIONS = [
    ("When was the Eiffel Tower completed?", "1889", True),
    ("Which city hosted the 2021 Summer Olympics?", "Tokyo", True),
    ("What river does Paris sit on?", "Seine", True),
    ("What is the largest city in Africa?", "Cairo", True),
    ("Where is the Great Pyramid of Giza?", "Giza", True),
    ("What is the capital of Brazil?", None, False),  # unanswerable -> must refuse
]

nb = c.post("/api/notebooks", json={"title": "eval"}).json()["id"]
for title, text in SOURCES:
    c.post(f"/api/notebooks/{nb}/sources:paste", json={"title": title, "text": text})

chunks = {}
for s in c.get(f"/api/notebooks/{nb}/sources").json():
    prev = c.get(f"/api/notebooks/{nb}/sources/{s['id']}/preview", params={"chars": 20000}).json()["text"]
    chunks[s["id"]] = prev

ok_answer, ok_cite, total_cite, refused = 0, 0, 0, 0
for q, expect, answerable in QUESTIONS:
    d = c.post(f"/api/notebooks/{nb}/chat", json={"message": q}).json()
    ans, cits = d["answer_md"], d["citations"]
    if not answerable:
        if "couldn't find" in ans.lower():
            refused = 1
            print(f"PASS refusal: {q}")
        else:
            print(f"FAIL refusal: {q} -> {ans[:80]}")
        continue
    hit = expect.lower() in ans.lower()
    ok_answer += hit
    for cit in cits:
        total_cite += 1
        src_text = chunks.get(cit["source_id"], "")
        if fuzz.partial_ratio(cit["quote"].lower(), src_text.lower()) >= 82:
            ok_cite += 1
    print(f"{'PASS' if hit else 'FAIL'} answer: {q} -> {ans[:90]}")

n_answerable = sum(1 for _, _, a in QUESTIONS if a)
print(f"\nanswer accuracy: {ok_answer}/{n_answerable}")
print(f"citation precision: {ok_cite}/{total_cite}")
print(f"refusal: {'PASS' if refused else 'FAIL'}")
score = (ok_answer / n_answerable) * 0.5 + (ok_cite / max(total_cite, 1)) * 0.4 + refused * 0.1
print(f"TOTAL: {score:.0%} {'PASS' if score >= 0.85 else 'FAIL (want >=85%)'}")
