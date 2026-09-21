# NotebookLM Clone — Master Plan
**Date:** 2026-09-21 | **Goal:** Build a full-featured, source-grounded AI research assistant ("NotebookLM clone")
**Method:** 4 parallel research agents → consolidated plan → verification → implementation spec

---

## 1. Parallel Agent Findings (Summary)

### Agent 1 — Core RAG Engine, Sources & Chat
- NotebookLM is a **closed RAG system**: answers come ONLY from user-uploaded sources, with inline citation chips linking to exact passages. If answer isn't in sources, it refuses rather than hallucinating.
- **Notebook = workspace** for a topic/project. Sources (left) + Chat (middle) + Studio (right) 3-column layout.
- **Per-source checkbox filtering**: by default all sources enabled; user can uncheck to scope the AI's "brain" per query (e.g. compare 2 authors only).
- **Source types supported:** PDF, DOCX, PPTX, TXT, Markdown, CSV, ePub, Google Docs/Slides/Sheets/Drive, images (PNG/JPG/WEBP/GIF), audio (MP3/WAV → transcribed), video (MP4), web URLs (text only, no paywall), public YouTube (transcript via captions), pasted text, Gemini chats, Deep Research live web sources.
- **Source limits:** 500,000 words or 200 MB per source; Slides ≤100 slides; Sheets ≤100k tokens.
- **Chat:** natural-language Q&A, suggested prompts, cited answers, "save to note", chat history.

### Agent 2 — Studio Panel (Generative Outputs)
9+ one-click tools, all **grounded in enabled sources with citations**:

| # | Tool | Output | Gen. time | Export |
|---|------|--------|-----------|--------|
| 1 | Audio Overview | 2-host podcast discussion (deep dive / brief / critique / debate), customizable focus, tone, length (2-3 / 5-6 / 8-10 min), 80+ languages, interactive mode | 3–8 min | MP3 download, public link, background play, speed control |
| 2 | Video Overview | Narrated visual summary (animated stills + graphics + narration) | 5–10 min | MP4 |
| 3 | Mind Map | Interactive concept diagram of cross-source relationships | 15–30s | Screenshot / interactive |
| 4 | Reports | Briefing docs, study guides, FAQs, timelines, SWOT, exec briefs | 30–90s | In-app / MD / PDF |
| 5 | Flashcards | Q&A cards with citations, count + difficulty + topic controls | 20–60s | In-app |
| 6 | Quiz | MCQ + short-answer + essay, hints, explanations, final score | 20–60s | In-app |
| 7 | Infographic | Visual summary poster | 60–180s | Image |
| 8 | Slide Deck | Presentation (~90s) | 60–90s | PPTX (editable text boxes) |
| 9 | Data Table | Structured extraction / comparison matrix | 30–120s | Google Sheets / CSV |
| 10 | Note | Rich-text editor, manual + AI-saved notes | instant | part of notebook |

- Suggested generation order for speed: Mind Map → Quiz → Flashcards → Report → Slides → Data Table → Audio → Video → Infographic.

### Agent 3 — UX, Sharing, Mobile, Privacy
- **3-column UI:** Sources (left, with add/search/list) | Chat (center, notebook title + source count + input) | Studio (right, artifact grid).
- **Notes:** rich-text editor; convert any chat answer to a note; notes can feed back as context.
- **Sharing:** private by default; invite-by-email private sharing; public link for notebooks and for Audio Overviews; team notebooks + analytics on paid tiers.
- **Mobile (iOS/Android):** ask questions, generate artifacts, background audio, speed control, offline download; desktop = full experience.
- **Privacy:** sources never used for model training; user can delete notebooks anytime; org controls (VPC-SC) on top tier.

### Agent 4 — Limits, Plans, Non-Functional Requirements
| Feature | Standard (free) | Plus | Pro | Ultra |
|---|---|---|---|---|
| Notebooks | 100 | 200 | 500 | 500–1000+ |
| Sources / notebook | 50 | 100 | 300 | 500–600 |
| Chats / day | 50 | 200 | 500 | 2,500–5,000 |
| Audio / Video per day | 3 | 6 | 20 | 100–200 |
| Reports/Quiz/Cards/MindMap per day | 10 each | 20 each | 100 each | 500–1000 each |
| Deep Research | 10/mo | 3/day | 20/day | 75–200/day |

- Quotas: daily reset 24h, monthly reset 30d. Prices approx: free $0, Plus ~$7.99/mo (bundled), Pro ~$19.99/mo, Ultra ~$249.99/mo.
- NFRs: grounding/citation accuracy, large context (up to 1M tokens class), low hallucination, fast Studio gens, scalable ingestion.

---

## 2. Complete Feature Inventory (what we must clone)

### P0 — Core (MVP)
1. Auth-less local user + multi-notebook CRUD (title, rename, delete, duplicate)
2. Source ingestion pipeline: upload (PDF/DOCX/PPTX/TXT/MD/CSV/EPUB/ images / audio) + URL import (web + YouTube transcript) + paste text
3. Source management: list, view/extracted-text preview, delete, enable/disable checkbox, per-source word counts
4. Text extraction + chunking + embeddings + vector retrieval (per-notebook namespace)
5. Grounded chat: retrieval → cited answer (quote + source name + chunk link), suggested prompts, "not in sources" refusal, chat history, save-to-note
6. Notes: rich-text CRUD, "save answer as note", insert note as query context
7. 3-column responsive UI + notebook dashboard

### P1 — Studio Text/Study Tools
8. Reports (study guide / briefing / FAQ / timeline / custom prompt)
9. Flashcards (count, difficulty, topic)
10. Quiz (MCQ/short/essay, interactive answering + score + hints)
11. Mind Map (interactive graph, click-to-expand, export PNG/SVG)
12. Data Table (column spec → table → CSV export)

### P2 — Studio Multimedia
13. Audio Overview: script generation (2-speaker) → TTS → MP3, focus/tone/length/language controls, player (speed, download)
14. Video Overview: script + slide images + narration → MP4 (ffmpeg slideshow)
15. Infographic: HTML/SVG template render → PNG
16. Slide Deck: outline → PPTX export (python-pptx)

### P3 — Power Features
17. Deep/Fast Research: web search → fetch top URLs → add as sources → synthesize report
18. Sharing: public read-only link (notebook + audio), private invite (simple token links for v1)
19. Mobile-friendly PWA: responsive + installable + offline audio
20. Usage quotas + plan tiers (configurable), background job queue with progress
21. Privacy: local-first storage, delete cascades, "no training" data policy notice

**Explicitly out of v1:** native iOS/Android apps, Google Drive OAuth, Sheets export API, VPC-SC, team analytics, watermarking.

---

## 3. Tech Stack (recommended, open + local-first)

- **Backend:** Python 3.11 + FastAPI + SQLite (metadata) + ChromaDB persistent (vectors, per-notebook collections) + background jobs (fastapi-background + file-based queue for v1, Celery/Redis optional later)
- **Ingestion:** pypdf + pdfminer fallback, python-docx, python-pptx, beautifulsoup4 + readability, youtube-transcript-api, whisper-fallback (faster-whisper optional), Pillow (images), openpyxl (CSV/XLSX)
- **RAG:** sentence-transformers (`all-MiniLM-L6-v2`) local embeddings default; chunking 800 tokens / 120 overlap; cosine top-k=8 with source filter; rerank optional (cross-encoder, P3)
- **LLM abstraction (`llm_provider`):** OpenAI-compatible API first (works with OpenAI, Gemini-OpenAI endpoint, Ollama, LM Studio), provider selectable via env; default prompts enforce grounding + citation JSON
- **TTS:** edge-tts (free, 2 voices, multi-language) default; optional OpenAI TTS / Piper; audio concat via ffmpeg
- **Video:** ffmpeg slideshow (PIL-rendered slides + narration) → MP4
- **Frontend:** React + Vite + Tailwind (3-column app) served by FastAPI in prod; PWA manifest
- **Exports:** python-pptx (slides), CSV, Markdown/PDF (reportlab/fpdf), PNG/SVG (mindmap via frontend canvas)

Why this stack: runs fully local except LLM (pluggable, incl. free Ollama), no vendor lock, matches sandbox preview (single port), easy to deploy (Docker + single binary).

---

## 4. Architecture

```
Browser (React SPA, 3-col UI + PWA)
   │ REST /api + SSE progress (/api/jobs/{id}/stream)
   ▼
FastAPI ──► SQLite (notebooks, sources, chunks-meta, chats, notes, artifacts, shares, quotas)
   ├──► Ingestion workers (extract → chunk → embed → Chroma upsert)
   ├──► RAG service (retrieve filtered → build prompt → LLM → parse citations → verify quotes)
   ├──► Studio workers (report/cards/quiz/mindmap/table/slides/infographic/audio/video/research)
   └──► Storage: /data/{notebook_id}/sources/*, artifacts/*.{mp3,mp4,pptx,png,md}
ChromaDB (persist dir) — one collection per notebook: nb_{id}
LLM provider (env: OPENAI_BASE_URL/KEY/MODEL or OLLAMA) │ TTS (edge-tts) │ ffmpeg
```

---

## 5. Phased Delivery Plan

| Phase | Scope | Exit criteria |
|-------|-------|---------------|
| **Phase 0** — Scaffold | Repo layout, FastAPI + React shells, SQLite schema, Chroma wiring, LLM ping, Docker, docs | `GET /api/health` OK, UI loads, `IMPLEMENTATION.md` approved |
| **Phase 1** — Core RAG (P0) | Notebooks, ingestion (file/URL/YouTube/paste), chunk+embed, grounded chat + citations, notes, dashboard | Upload 3 PDFs → ask → cited answer; save-to-note; source toggle changes answer |
| **Phase 2** — Studio Study (P1) | Reports, Flashcards, Quiz, Mind Map, Data Table + CSV | Each artifact generates <120s with citations; quiz scoring works |
| **Phase 3** — Studio Media (P2) | Audio (script+TTS+MP3+player), Video (MP4), Infographic (PNG), Slide Deck (PPTX) | 5-min audio from 3 sources; video plays; PPTX opens in PowerPoint |
| **Phase 4** — Power (P3) | Web research, share links, quotas/tiers, PWA/offline audio, polish + eval harness | Public link works; quota enforced; Lighthouse PWA pass; citation-precision eval ≥85% |
| **Phase 5** — Harden | Tests, evals, Docker prod, README, demo seed data, cleanup | `pytest` green, demo notebook seeded, docs complete |
| **Phase 6** — Jobs+Polish ✅ | bg jobs + SSE progress, mindmap SVG export, infographic themes, quotas UI, Docker | audio/video progress live; 8/8 tests |
| **Phase 7** — PDF+Brand ✅ | Report/Note PDF (fpdf2), milky/ink/gold theme (UI + artifacts), fonts in Docker | PDF valid; 9/9 tests |
| **Phase 8** — Plan gaps ✅ | MiniLM embeddings (auto-fallback), mindmap tree+PNG, audio speed, duplicate, note-context, smart-pause, seed script | eval ≥85%; tests green |
| **Phase 9** — Plan closure ✅ | Cross-encoder rerank (reorder-only), viewArt repair (9 live viewers), chat-history/suggest verified, PWA verified, footer policy notice, manifest brand, ruff, demo script | eval ≥85%; ruff clean; 1 script block |
| **Phase 10** — Teams ✅ | pbkdf2 users + sessions, members/roles, usage_log analytics, AUTH_REQUIRED=0 default | register→share→analytics flow; eval ≥85% |
| **Phase 11** — Google ✅ | Drive OAuth import (docs/sheets/slides export), Sheets push, creds-gated graceful | status/auth-url/files/sheets endpoints green |
| **Phase 12** — Ship ✅ | PWA icons, demo-seed endpoint, backup script, deps verify, .dockerignore, docs | ruff clean; venv install ok |
| **Phase 13** — Everywhere ✅ | Windows bat/ps1/exe-spec, macOS .command, Linux installer+desktop+systemd, iOS/Android PWA guide, release script | scripts lint; meta served; docs |
| **Phase 14** — Native iOS ✅ | SwiftUI app (13 files) + hand-generated .xcodeproj + AppIcon + ATS LAN + README-iOS | project refs resolve; swift sanity; needs Mac to compile |

---

## 6. Risks & Mitigations
- LLM hallucination → strict grounded prompts + quote verification (fuzzy match against chunks; drop unverified claims) + "not in sources" path.
- Long audio/video gens → background jobs + SSE progress + local caching.
- Large PDFs (500k words) → streaming extraction, chunked embedding batches, per-source caps configurable.
- No API keys in sandbox → Ollama/mock provider fallback so UI works offline; clear `.env` setup.
- Scope creep → P0→P3 gating; each phase demoable independently.

---

## 7. v2 — Complete App (this build)
**Goal:** close the v1 deferrals + shippable product. Non-goals (stay out): native iOS/Android (PWA instead), VPC-SC, watermarking.
- **Teams:** opt-in auth (`AUTH_REQUIRED=0` default preserves auth-less local). First user = admin. Roles: owner/editor/viewer.
- **Google:** OAuth web flow, tokens in DB. Scopes: `drive.readonly` + `spreadsheets`. No creds → endpoints return setup JSON, UI shows setup hint.
- **Analytics:** separate `usage_log(day,who,counter)` table — global quota PK untouched.
- **Ship:** 192/512/maskable icons, `scripts/backup.sh`, demo-seed endpoint, requirements verified in clean venv, Dockerfile statically verified (no docker daemon in sandbox).
