# 📓 NotebookLM Clone (local-first)

A source-grounded AI research assistant in the spirit of Google's NotebookLM:
upload your documents → chat with them (every claim cited) → generate podcasts,
videos, quizzes, flashcards, mind maps, reports, slides, infographics & data tables.

Docs: [`PLAN.md`](PLAN.md) (master plan) · [`PLAN_CHECK.md`](PLAN_CHECK.md)
(verification) · [`IMPLEMENTATION.md`](IMPLEMENTATION.md) (build contract).

## ✨ Features (complete app: v1 + v2)

| Area | What's included |
|---|---|
| 📓 Notebooks | CRUD, dashboard stats, duplicate-friendly |
| 📚 Sources | PDF, DOCX, PPTX, TXT/MD/CSV, web URL, YouTube transcript, pasted text, **Google Drive import** (OAuth) — with per-source enable/disable toggles + text preview |
| 💬 Chat | Grounded Q&A, inline citation chips, fuzzy-verified quotes, "not in sources" refusal, suggested prompts, history, save-answer-as-note |
| 📝 Notes | Rich-text CRUD, one-click notes from any chat answer |
| ✨ Studio (9 tools) | **Report, Flashcards, Quiz (scored), Mind Map, Data Table (+CSV, **Send to Google Sheets**), Audio Overview (MP3 + chapters), Video Overview (MP4), Slide Deck (PPTX), Infographic (PNG)** · Report→PDF, Note→PDF |
| 🔎 Research | Web search (DDG → Wikipedia fallbacks) auto-imports top results as sources + writes a briefing report |
| 🧭 Understanding Agent | Reads a learner's goal plus enabled sources, then recommends a grounded beginner/general/advanced learning route |
| 🔗 Sharing | Token-based public links: human HTML page (`/s/:token`) + JSON API |
| 📊 Quotas | Daily chat/studio/research counters with UI banner |
| 📱 PWA | Installable (192/512/maskable icons), offline shell caching, background audio |
| 👥 Teams | Optional login (`AUTH_REQUIRED=1`): users, notebook members (viewer/editor/owner), per-user activity analytics |
| 💾 Backup | `scripts/backup.sh` → timestamped tarball of DB + uploads + artifacts |
| 🧠 Retrieval | TF-IDF default · MiniLM dense embeddings auto-used when installed · cross-encoder rerank (RERANK=auto\|off) |
| 🔒 Privacy | Local SQLite + files; delete cascades; nothing trains any model |

Works **fully offline** (mock LLM + mock TTS) and upgrades automatically with
real providers (OpenAI-compatible / Ollama for text, edge-tts voices for audio).

### Personal agent and future Google integrations

The **Understanding Agent** is deliberately local and source-grounded today: it
chooses a clear next format and learning path from the learner's stated goal.
The Integrations status API also exposes a safe capability catalog for optional
Google AI/Vertex, Speech-to-Text, and video-generation providers. Those three
are marked `planned`: no credentials, microphone capture, or remote generation
is activated until a provider adapter is intentionally configured. Google Drive
and Sheets OAuth remain the currently supported Google connection.

## 🖥️ Install everywhere
Windows · macOS · Linux · iPhone/iPad · Android → **[docs/INSTALL.md](docs/INSTALL.md)**

## 🚀 Quickstart

```bash
cd notebooklm-clone
./start.sh            # installs deps + serves on http://localhost:8000
```

Or manually:

```bash
cd notebooklm-clone/backend
pip install -r requirements.txt
STORAGE_DIR=../data LLM_PROVIDER=mock python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For real AI answers, copy `.env.example` → `.env` and set one of:

```bash
LLM_PROVIDER=openai  OPENAI_API_KEY=sk-...  LLM_MODEL=gpt-4o-mini
# or local & free:
LLM_PROVIDER=ollama  OLLAMA_URL=http://localhost:11434  LLM_MODEL=llama3.1
```

## 🐳 Docker

```bash
docker compose up --build     # api on :8000, data persisted in ./data
```

## 🧪 Tests & eval

```bash
cd backend
python -m pytest tests/ -q   # full suite: RAG, all 9 Studio tools, quotas, sharing
python eval.py               # citation precision/recall eval (target ≥85%)
```

## 🗂 Layout

```
notebooklm-clone/
├── PLAN.md / PLAN_CHECK.md / IMPLEMENTATION.md / README.md
├── start.sh                 # one-shot installer + server
├── backend/
│   ├── app/main.py          # FastAPI: notebooks/sources/chat/notes/studio/research/share
│   ├── app/media.py         # Phase 3: TTS + audio/video/slides/infographic builders
│   ├── app/static/          # single-file 3-column web UI + PWA manifest/SW
│   ├── tests/test_core.py   # pytest suite (offline)
│   └── eval.py              # grounding eval harness
└── data/                    # SQLite + uploads + artifacts (gitignored)
```

## 🔌 API sketch

```
GET  /api/health  /api/quotas
CRUD /api/notebooks   (+ /stats)
POST /api/notebooks/:id/sources:file|:url|:youtube|:paste
POST /api/notebooks/:id/chat   → {answer_md, citations[]}
CRUD /api/notebooks/:id/notes  (+ /notes:from-chat)
POST /api/notebooks/:id/studio/:kind   (report|flashcards|quiz|mindmap|datatable|audio|video|slides|infographic)
GET  /api/artifacts/:id[/download]
POST /api/notebooks/:id/research   GET /s/:token
POST .../studio/:kind?bg=1  → {job_id}   GET /api/jobs/:jid[/stream] (SSE progress)
```

## ⚠️ Notes

- Audio uses edge-tts voices when reachable, else offline placeholder tones
  (real voice on any normal network; the sandbox IP is rate-limited by Microsoft).
- Video/slides/infographic render locally (ffmpeg via imageio-ffmpeg + Pillow).
- Long audio/video generations run as background jobs with live SSE progress bars.
