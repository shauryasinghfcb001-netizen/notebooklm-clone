# NotebookLM Clone — Implementation Spec
Companion to `PLAN.md`. This is the build contract: schemas, APIs, pipelines, prompts, tasks.

---

## 1. Repo Layout

```
notebooklm-clone/
├── PLAN.md
├── IMPLEMENTATION.md   (this file)
├── PLAN_CHECK.md
├── README.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, static serve, SSE
│   │   ├── config.py          # env: LLM, TTS, limits, storage paths
│   │   ├── db.py              # sqlite init + helpers
│   │   ├── models.py          # pydantic schemas
│   │   ├── api/
│   │   │   ├── notebooks.py   # CRUD notebooks + dashboard stats
│   │   │   ├── sources.py     # upload/URL/YouTube/paste + list/toggle/delete/preview
│   │   │   ├── chat.py        # query + history + save-to-note + suggestions
│   │   │   ├── notes.py       # notes CRUD
│   │   │   ├── studio.py      # create/list/get artifacts (all 9 tools) + download
│   │   │   ├── research.py    # deep/fast research jobs
│   │   │   ├── share.py       # public/private links
│   │   │   └── jobs.py        # job status + SSE stream
│   │   ├── services/
│   │   │   ├── ingest.py      # extractors per type + chunker
│   │   │   ├── vectors.py     # chroma per-notebook collections
│   │   │   ├── rag.py         # retrieve → prompt → generate → verify citations
│   │   │   ├── llm.py         # provider abstraction (openai-compatible/ollama/mock)
│   │   │   ├── prompts.py     # all system/user prompt templates
│   │   │   ├── studio_text.py # report/flashcards/quiz/mindmap/datatable
│   │   │   ├── studio_media.py# audio/video/infographic/slides
│   │   │   ├── tts.py         # edge-tts wrapper, 2-voice dialogue
│   │   │   ├── video.py       # PIL slides + ffmpeg mux
│   │   │   ├── research_svc.py# web search (duckduckgo) + fetch + synthesize
│   │   │   └── quotas.py      # daily/monthly counters
│   │   └── jobs.py            # file-backed job queue + progress events
│   ├── requirements.txt
│   └── tests/test_rag_verify.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # router: dashboard + notebook 3-col view
│   │   ├── api.js             # fetch wrappers + SSE client
│   │   ├── components/        # SourcePanel, ChatPanel, StudioPanel, NotesDrawer,
│   │   │                      # CitationChip, AudioPlayer, MindMapView, QuizView,
│   │   │                      # FlashcardView, DataTableView, ShareModal, JobProgress
│   │   └── styles.css         # tailwind
│   ├── index.html, vite.config.js, tailwind.config.js, package.json
└── data/  (gitignored; sqlite + chroma + uploads + artifacts)
```

---

## 2. Data Model (SQLite)

```sql
notebooks(id TEXT PK, title TEXT, created_at, updated_at, icon TEXT);
sources(id TEXT PK, notebook_id FK, kind TEXT, -- pdf,docx,pptx,txt,md,csv,epub,url,youtube,paste,audio,image
  title TEXT, uri TEXT, enabled INTEGER DEFAULT 1, status TEXT, -- pending,ready,error
  word_count INTEGER, char_count INTEGER, error TEXT, created_at);
chunks(id TEXT PK, notebook_id FK, source_id FK, idx INTEGER, text TEXT, token_est INTEGER);
chats(id TEXT PK, notebook_id FK, role TEXT, content TEXT, citations_json TEXT, created_at);
notes(id TEXT PK, notebook_id FK, title TEXT, content_md TEXT, from_chat_id TEXT, created_at, updated_at);
artifacts(id TEXT PK, notebook_id FK, kind TEXT, -- report,flashcards,quiz,mindmap,datatable,audio,video,infographic,slides
  title TEXT, params_json TEXT, content_json TEXT, file_path TEXT, status TEXT, created_at);
shares(id TEXT PK, notebook_id FK, kind TEXT, -- notebook,audio,artifact
  token TEXT UNIQUE, artifact_id TEXT, created_at, expires_at);
usage(day TEXT, notebook_scope TEXT, counter TEXT, n INTEGER, PRIMARY KEY(day, notebook_scope, counter));
jobs(id TEXT PK, kind TEXT, notebook_id FK, status TEXT, progress INTEGER, message TEXT, result_json TEXT, created_at, updated_at);
```

Vectors in Chroma: collection `nb_{notebook_id}`, metadata `{source_id, chunk_id, idx}`.

---

## 3. REST API Contract (v1)

```
GET  /api/health → {ok, llm_provider, llm_ok, tts_ok, ffmpeg_ok}
CRUD /api/notebooks [+ GET /api/notebooks/:id/stats]
POST /api/notebooks/:id/sources:file        (multipart: file, title?)
POST /api/notebooks/:id/sources:url         {url}
POST /api/notebooks/:id/sources:youtube     {url}
POST /api/notebooks/:id/sources:paste       {title, text}
GET  /api/notebooks/:id/sources
PATCH /api/notebooks/:id/sources/:sid       {enabled, title}
DELETE /api/notebooks/:id/sources/:sid
GET  /api/notebooks/:id/sources/:sid/preview (?chars=4000)
POST /api/notebooks/:id/chat                {message, only_source_ids?} → {answer_md, citations[]}
GET  /api/notebooks/:id/chat                (history)
POST /api/notebooks/:id/chat:suggest        → {prompts[3]}
CRUD /api/notebooks/:id/notes (+ POST /from-chat {chat_id})
POST /api/notebooks/:id/studio/:kind        (params per tool) → {job_id}
GET  /api/notebooks/:id/studio              (list artifacts)
GET  /api/artifacts/:aid (+ /download)
POST /api/notebooks/:id/research            {query, depth} → {job_id}
CRUD /api/notebooks/:id/shares
GET  /api/jobs/:jid  +  GET /api/jobs/:jid/stream (SSE)
GET  /s/:token  (public share page, read-only JSON+HTML)
```

Citation object: `{source_id, source_title, chunk_id, quote, char_start}`.

---

## 4. RAG Pipeline (core correctness)

1. **Ingest:** detect kind → extract raw text (+page/slide markers) → normalize whitespace → word count → enforce cap (default 500k words / 200MB, configurable).
2. **Chunk:** ~800 tokens (≈600 words) with 120-token overlap; keep `page` hints where available; store in SQLite + embed in batches of 32.
3. **Embed:** `sentence-transformers/all-MiniLM-L6-v2` local; normalize vectors; Chroma HNSW.
4. **Retrieve:** filter `source_id in enabled`; top_k=8 (chat) / 12 (reports/audio scripts); MMR-lite dedupe by source diversity (max 3 chunks/source for chat).
5. **Generate:** system prompt = grounded-only + citation-JSON instruction; user prompt = question + numbered context blocks `[S1 title …]`.
6. **Verify:** for each returned citation quote, fuzzy-match (ratio ≥0.82, rapidfuzz) against its chunk; drop unmatched citations; if zero verified and answer is factual → replace with "not in sources" template.
7. **Render:** markdown answer + citation chips `[1][2]` mapping to preview spans.

---

## 5. Prompt Templates (key excerpts)

- **CHAT_SYSTEM:** "You answer ONLY from the provided source passages. Every factual sentence must cite [n]. If the answer is not in the passages, say exactly: 'I couldn't find this in your enabled sources.' Never use outside knowledge… Return JSON: {answer_md, citations:[{ref, source_id, quote}]}".
- **REPORT:** role=analyst; sections per type (briefing/study-guide/FAQ/timeline/custom); citations per bullet.
- **FLASHCARDS:** "Generate exactly N cards {difficulty} about {topic}. JSON list {front, back, source_ref}."
- **QUIZ:** "Generate Q questions mixed {types}. JSON {questions:[{q, type, choices?, answer, explanation, source_ref}]}."
- **MINDMAP:** "Extract central topic + branches. JSON {root, nodes:[{id,label,children:[ids]}]} max 40 nodes."
- **DATATABLE:** "Extract rows with columns [..]. JSON {columns[], rows[][]}; empty string if missing."
- **AUDIO_SCRIPT:** "Write a 2-host podcast (Host A curious, Host B expert), {length} min ≈ {words} words, focus: {focus}, tone {tone}, level {level}. Ground every claim in sources; include citation markers. Output JSON {turns:[{speaker, text}]}."
- **VIDEO_SCRIPT:** like audio + `{slides:[{title, bullets[], narration}]}` 6–10 slides.

---

## 6. Studio Params & Outputs

| Tool | Params | Output |
|---|---|---|
| report | `{type: briefing\|study-guide\|faq\|timeline\|custom, custom_prompt?, max_words?}` | `content_json.md` + citations |
| flashcards | `{count 5–50, difficulty: easy\|medium\|hard\|mixed, topic?}` | `cards[]` |
| quiz | `{count 3–20, types[], difficulty}` | `questions[]`, scored client-side + server key |
| mindmap | `{max_nodes?, focus?}` | `graph {root, nodes, edges}` |
| datatable | `{columns[] or goal, max_rows?}` | `columns/rows` + CSV file |
| audio | `{length: brief\|standard\|extended, focus?, tone?, level?, language?}` | dialogue turns + `audio.mp3` + chapters |
| video | `{length, focus?, resolution?}` | slides + narration + `video.mp4` |
| infographic | `{theme?, focus?}` | `infographic.png` (SVG→PNG) |
| slides | `{slide_count?, theme?}` | `slides.pptx` |

All studio runs are **async jobs** with SSE progress (`queued → retrieving → generating → rendering → done`).

---

## 7. TTS / Audio / Video Details

- **TTS default:** `edge-tts` voices (e.g. `en-US-AriaNeural` + `en-US-GuyNeural`); per-turn synthesis then ffmpeg concat with 250ms gaps; language map for 80+ locales (best-effort voice pick).
- **Fallbacks:** OpenAI TTS if `OPENAI_API_KEY` set and `TTS_PROVIDER=openai`; mock TTS (sine beep) when offline so pipeline is testable.
- **Video:** PIL-rendered 1280×720 slides (title + bullets + page bg) → per-slide PNG durations from narration length → ffmpeg concat + AAC audio → H.264 MP4.
- **Infographic:** server-rendered SVG template (title, 5 stats, timeline, quotes) → PNG via cairosvg (fallback: PIL).

---

## 8. Research (Deep/Fast)

- `POST /research {query, depth: fast|deep}` → DuckDuckGo search (no key) top 5/12 → readability extract → auto-add as `url` sources (tagged `via:research`) → RAG synthesize report artifact. Respects quota table.

---

## 9. Quotas & Config (.env)

```
LLM_PROVIDER=openai|ollama|mock        LLM_MODEL=gpt-4o-mini (or llama3.1)
OPENAI_BASE_URL=...  OPENAI_API_KEY=...  OLLAMA_URL=http://localhost:11434
TTS_PROVIDER=edge|openai|mock          FFMPEG_BIN=ffmpeg
EMBED_MODEL=all-MiniLM-L6-v2
LIMIT_SOURCES_PER_NOTEBOOK=50  LIMIT_WORDS_PER_SOURCE=500000
LIMIT_CHATS_PER_DAY=50  LIMIT_AUDIO_PER_DAY=3  LIMIT_STUDIO_PER_DAY=10
STORAGE_DIR=./data  PUBLIC_BASE_URL=http://localhost:8000
```

---

## 10. Frontend Pages/Components

- **Dashboard:** notebook cards (title, sources count, updated), new/delete/duplicate, quota banner.
- **Notebook view (3-col):** `SourcePanel` (add menu: file/URL/YouTube/paste; search; list with checkbox + status + word count + preview modal) | `ChatPanel` (title, source-count, messages with chips, suggestion prompts, input, save-to-note) | `StudioPanel` (9 tool buttons + artifact list + viewers) + `NotesDrawer` toggle.
- **Viewers:** Markdown+citations, Quiz runner, Flashcards flipper, MindMap (SVG tree), DataTable (+CSV), Audio player (speed/download/chapters), Video player, Share modal (copy link).
- **PWA:** manifest + service worker caching shell + downloaded audio.

---

## 11. Phase Task Checklists

### Phase 0 — Scaffold (this week)
- [x] backend skeleton (main/config/db/models), /health, static frontend serve
- [x] frontend shell (dashboard + 3-col empty states), api.js
- [x] docker-compose (api + optional ollama), .env.example, README quickstart
- [x] mock LLM provider so everything runs without keys

### Phase 1 — Core RAG
- [x] extractors: pdf/docx/pptx/txt/md/csv/epub/image-ocr-skip/audio-transcribe-note/url/youtube/paste
- [x] chunk+embed+chroma; source toggle filtering; delete cascades
- [x] chat endpoint + verify + history + suggestions + save-to-note
- [x] notes CRUD; dashboard stats; seed demo notebook

### Phase 2 — Studio Study
- [x] report/flashcards/quiz/mindmap/datatable endpoints + frontend viewers + CSV export

### Phase 3 — Studio Media
- [x] tts dialogue + concat; audio job + player page; video mux; infographic; pptx

### Phase 4 — Power
- [x] research, shares (/s/:token), quotas, PWA, eval script (`backend/eval.py`: citation precision/recall on seed set)

### Phase 5 — Harden
- [x] pytest 11/11, ruff clean, README + DEMO_SCRIPT.md, viewArt repair, cleanup

---

## 12. Acceptance Tests (per phase gate)
- P1: 3 PDFs → chat returns ≥1 verified citation; disabling the key source flips answer to "not in sources"; save-to-note round-trips.
- P2: each study artifact <120s, valid JSON schema, CSV/PNG open correctly.
- P3: audio MP3 plays with 2 distinct voices; video MP4 <50MB plays; PPTX opens with editable boxes.
- P4: public link renders without login; quota 51st chat blocked with friendly message; research adds ≥3 sources.

---

## 13. v2 — Complete App Build Spec
### Schema (new)
- `users(id, username UNIQUE, pw_hash, role, created_at)`; `sessions(token PK, user_id, expires_at, created_at)`
- `members(notebook_id, user_id, role, PK(nb,user))`; `usage_log(day, who, counter, n, PK(day,who,counter))`
- `integrations(provider PK, token_json, updated_at)`; `notebooks.owner_id` (NULL = legacy open)
### Roles
| | read/chat | sources/studio/notes | members/delete |
|---|---|---|---|
| viewer | ✅ | ❌ | ❌ | editor | ✅ | ✅ | ❌ | owner | ✅ | ✅ | ✅ |
### Endpoints
- `POST /api/auth/register|login|logout`, `GET /api/auth/me`
- `GET/POST /api/notebooks/{id}/members`, `DELETE .../members/{uid}`, `GET /api/analytics?days=14`
- `GET /api/integrations/status`, `GET /api/integrations/drive/auth-url`, `GET .../drive/callback`, `GET .../drive/files?q=`, `POST /api/notebooks/{id}/sources:drive`, `POST /api/artifacts/{id}:sheets`
- `POST /api/demo:seed`
### UI map
Login overlay (init→me), Drive picker (sources panel), Sheets button (datatable viewer), Share w/ user (nb toolbar), Team analytics (dash), Demo seed (dash), first-run hint.
### Checklist
- [x] Phase 10 — Teams: auth, members, analytics; eval 94%
- [x] Phase 11 — Google: drive import, sheets push; graceful unconfigured
- [x] Phase 12 — Ship: icons, seed endpoint, backup, venv deps, ruff, docs
- [x] Phase 13 — Everywhere: per-OS launchers, exe kit, PWA meta, INSTALL.md
- [x] Phase 14 — Native iOS: SwiftUI client, xcodeproj gen, AppIcon, build guide
