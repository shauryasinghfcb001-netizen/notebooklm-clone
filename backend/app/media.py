"""Phase 3 media pipeline: Audio / Video / Slides / Infographic.

All builders work OFFLINE (mock script + mock TTS beeps) and upgrade
automatically when an LLM and/or edge-tts network are available.
"""
from __future__ import annotations

import array
import math
import re
import shutil
import subprocess
import textwrap
import wave
from pathlib import Path

RATE = 22050

# Brand palette: 60% milky white / 40% ink black / 2% gold
MILK = (250, 246, 236)
INK = (11, 11, 12)
GOLD = (201, 162, 39)

# ---------------- ffmpeg ----------------
def get_ffmpeg():
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        return p if Path(p).exists() else None
    except Exception:
        return None

def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)

# ---------------- voices ----------------
VOICES = {"A": "en-US-AriaNeural", "B": "en-US-GuyNeural"}
LANG_VOICES = {
    "en": ("en-US-AriaNeural", "en-US-GuyNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "hi": ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
}
def pick_voices(lang: str):
    return LANG_VOICES.get((lang or "en")[:2], VOICES["A"] and (VOICES["A"], VOICES["B"]))

AUDIO_WORDS = {"brief": 400, "standard": 800, "extended": 1300}

# ---------------- script generation ----------------
def sentences_of(picked, max_sents=60):
    out = []
    for ch in picked:
        for s in re.split(r"(?<=[.!?])\s+", ch["text"]):
            s = s.strip()
            if len(s) > 25:
                out.append((s, ch))
            if len(out) >= max_sents:
                return out
    return out

def mock_audio_script(picked, params):
    budget = AUDIO_WORDS.get(params.get("length", "standard"), 800)
    focus = params.get("focus", "the key ideas")
    sents = sentences_of(picked)
    turns = [{"speaker": "A", "text": f"Welcome! Today we're digging into {focus}. Let's break it down."}]
    words = 15
    i = 0
    while words < budget and i < len(sents):
        _s, ch = sents[i]
        title = ch.get("stitle", "the sources")
        q = f"So what do we learn from {title}?"
        turns.append({"speaker": "A", "text": q}); words += len(q.split())
        chunk_lines = []
        for s2, _ in sents[i:i+2]:
            chunk_lines.append(s2)
        b = " ".join(chunk_lines)
        turns.append({"speaker": "B", "text": b}); words += len(b.split())
        i += 2
    turns.append({"speaker": "A", "text": "That's a great overview. Thanks for listening!"})
    return {"turns": turns, "focus": focus}

async def gen_audio_script(picked, params, gen_json):
    if gen_json is None:
        return mock_audio_script(picked, params)
    budget = AUDIO_WORDS.get(params.get("length", "standard"), 800)
    ctx = "\n\n".join(f"[{i+1}] ({ch.get('stitle','')})\n{ch['text'][:2000]}" for i, ch in enumerate(picked[:10]))
    try:
        raw = await _maybe(gen_json,
            "Return STRICT JSON {\"turns\": [{\"speaker\": \"A\"|\"B\", \"text\": \"...\"}]} — a natural 2-host podcast.",
            f"Write a 2-host podcast (A curious, B expert), ~{budget} words total. Focus: {params.get('focus','key ideas')}. "
            f"Tone: {params.get('tone','conversational')}. Audience level: {params.get('level','general')}. "
            f"Ground every claim in the passages; do not invent facts.\n\nPASSAGES:\n{ctx}")
        turns = raw.get("turns", [])
        if len(turns) >= 3:
            return {"turns": turns, "focus": params.get("focus", "")}
    except Exception:
        pass
    return mock_audio_script(picked, params)

async def _maybe(fn, *a):
    import asyncio
    r = fn(*a)
    return await r if asyncio.iscoroutine(r) else r

def mock_video_slides(picked, params, max_slides=8):
    sents = sentences_of(picked)
    by_src: dict[str, list] = {}
    for s, ch in sents:
        by_src.setdefault(ch.get("stitle", "Overview"), []).append(s)
    slides = []
    for title, ss in list(by_src.items())[:max_slides]:
        bullets = [s[:110] for s in ss[:3]]
        slides.append({"title": title[:60], "bullets": bullets,
                       "narration": " ".join(ss[:2])[:600]})
    if not slides:
        slides = [{"title": "Overview", "bullets": ["No content"], "narration": "No content available."}]
    return slides

async def gen_video_slides(picked, params, gen_json):
    if gen_json is None:
        return mock_video_slides(picked, params)
    ctx = "\n\n".join(f"[{i+1}] ({ch.get('stitle','')})\n{ch['text'][:1800]}" for i, ch in enumerate(picked[:10]))
    try:
        raw = await _maybe(gen_json,
            "Return STRICT JSON {\"slides\": [{\"title\": \"...\", \"bullets\": [\"...\",\"...\"], \"narration\": \"...\"}]} (6-8 slides).",
            f"Create 6-8 video slides with narration. Focus: {params.get('focus','key ideas')}.\n\nPASSAGES:\n{ctx}")
        if raw.get("slides"):
            return raw["slides"][:8]
    except Exception:
        pass
    return mock_video_slides(picked, params)

# ---------------- TTS ----------------
async def synth_turn(text, voice, speaker, out_mp3: Path, tts_provider: str, ff: str | None) -> Path:
    """Synthesize one turn. Returns path to a NORMALIZED wav (22050Hz mono)."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    norm = out_mp3.with_suffix(".norm.wav")
    if tts_provider == "edge":
        try:
            import edge_tts
            await edge_tts.Communicate(text[:4000], voice).save(str(out_mp3))
            if ff:
                run([ff, "-y", "-i", str(out_mp3), "-ar", str(RATE), "-ac", "1", str(norm)])
                return norm
            return out_mp3
        except Exception:
            pass  # fall through to mock
    mock_say(text, speaker, norm)
    return norm

def mock_say(text, speaker, out_wav: Path) -> float:
    dur = min(60.0, max(1.5, len(text) / 13.0))
    freq = 392.0 if speaker == "A" else 523.25
    n = int(dur * RATE)
    frames = array.array("h")
    for i in range(n):
        t = i / RATE
        env = min(1.0, t * 5, max(0.0, (dur - t)) * 5)
        v = int(9000 * env * math.sin(2 * math.pi * freq * t) * (0.65 + 0.35 * math.sin(2 * math.pi * 2.5 * t)))
        frames.append(v)
    with wave.open(str(out_wav), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(frames.tobytes())
    return dur

def wav_duration(p: Path) -> float:
    try:
        with wave.open(str(p)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return 2.0

def concat_wavs(parts: list[Path], out: Path):
    with wave.open(str(out), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        for p in parts:
            try:
                with wave.open(str(p)) as r:
                    w.writeframes(r.readframes(r.getnframes()))
            except Exception:
                continue
            # 250ms gap
            w.writeframes(b"\x00\x00" * int(RATE * 0.25))

async def build_audio(work: Path, turns: list, language="en", tts_provider="edge", prog=None, smart_pause=False):
    work.mkdir(parents=True, exist_ok=True)
    ff = get_ffmpeg()
    va, vb = pick_voices(language)
    parts, chapters, t = [], [], 0.0
    for i, turn in enumerate(turns):
        sp = "A" if turn.get("speaker", "A") != "B" else "B"
        norm = await synth_turn(turn["text"], va if sp == "A" else vb, sp,
                                work / f"turn_{i:02d}.mp3", tts_provider, ff)
        d = wav_duration(norm) if norm.suffix == ".wav" else 5.0
        parts.append(norm)
        chapters.append({"n": i + 1, "speaker": sp, "start": round(t, 2),
                         "title": " ".join(turn["text"].split()[:7])})
        t += d + 0.25
        if prog:
            prog((i + 1) / max(1, len(turns)) * 0.9, f"synthesizing turn {i + 1}/{len(turns)}")
    full_wav = work / "full.wav"
    if prog:
        prog(0.93, "encoding audio")
    concat_wavs([p for p in parts if p.suffix == ".wav"], full_wav)
    # encode final
    final_mp3 = work / "audio.mp3"
    if ff:
        af = ["-af", "silenceremove=start_periods=1:start_duration=0.4:start_threshold=-45dB"] if smart_pause else []
        try:
            run([ff, "-y", "-i", str(full_wav), *af, "-c:a", "libmp3lame", "-b:a", "128k", str(final_mp3)])
            return final_mp3, chapters, round(t, 1)
        except Exception:
            pass
        try:
            m4a = work / "audio.m4a"
            run([ff, "-y", "-i", str(full_wav), "-c:a", "aac", str(m4a)])
            return m4a, chapters, round(t, 1)
        except Exception:
            pass
    return full_wav, chapters, round(t, 1)

# ---------------- PIL rendering ----------------
def _font(bold=False, size=40):
    from PIL import ImageFont
    cands = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()

def render_slide_png(path: Path, kicker: str, title: str, bullets: list, footer="NotebookLM Clone",
                     W=1280, H=720):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), MILK)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill=INK)
    d.text((60, 34), kicker[:60], font=_font(False, 30), fill=GOLD)
    for j, line in enumerate(textwrap.wrap(title, 34)[:2]):
        d.text((60, 70 + j * 40), line, font=_font(True, 34), fill=(255, 255, 255))
    y = 210
    for b in bullets[:5]:
        for line in textwrap.wrap("•  " + b, 52)[:3]:
            d.text((70, y), line, font=_font(False, 30), fill=(20, 20, 22))
            y += 42
        y += 10
    d.text((60, H - 50), footer[:80], font=_font(False, 22), fill=(146, 124, 52))
    img.save(path)

IG_THEMES = {
    "blue": {"band": (11, 87, 208), "bg": (248, 250, 252), "accent": (11, 87, 208), "sub": (191, 219, 254), "footer": (100, 116, 139)},
    "green": {"band": (19, 115, 51), "bg": (243, 248, 244), "accent": (19, 115, 51), "sub": (200, 230, 210), "footer": (100, 116, 139)},
    "dark": {"band": (15, 23, 42), "bg": (30, 41, 59), "accent": (59, 130, 246), "sub": (148, 197, 255), "footer": (148, 163, 184)},
    "brand": {"band": INK, "bg": MILK, "accent": GOLD, "sub": (232, 206, 132), "footer": (130, 117, 80)},
}


def render_infographic_png(path: Path, title: str, points: list, stats: dict, theme="brand"):
    from PIL import Image, ImageDraw
    W, H = 1080, 300 + 150 * min(max(len(points), 3), 7)
    th = IG_THEMES.get(theme, IG_THEMES["brand"])
    img = Image.new("RGB", (W, H), th["bg"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 190], fill=th["band"])
    for j, line in enumerate(textwrap.wrap(title, 30)[:2]):
        d.text((50, 45 + j * 55), line, font=_font(True, 52), fill=(255, 255, 255))
    d.text((50, 155), f"{stats.get('sources',0)} sources · {stats.get('words',0)} words", font=_font(False, 26), fill=(191, 219, 254))
    y = 230
    for i, p in enumerate(points[:7]):
        d.rounded_rectangle([40, y, W - 40, y + 120], radius=18, fill=(255, 255, 255), outline=(226, 232, 240), width=2)
        d.ellipse([58, y + 30, 108, y + 80], fill=th["accent"])
        d.text((72, y + 38), str(i + 1), font=_font(True, 30), fill=(255, 255, 255))
        for k, line in enumerate(textwrap.wrap(p, 62)[:3]):
            d.text((125, y + 22 + k * 32), line, font=_font(False, 24), fill=(30, 41, 59))
        y += 140
    d.text((50, H - 40), "Generated from your sources · NotebookLM Clone", font=_font(False, 22), fill=th["footer"])
    img.save(path)

# ---------------- video ----------------
async def build_video(work: Path, slides: list, language="en", tts_provider="edge", prog=None):
    ff = get_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg not available — video needs imageio-ffmpeg (pip install imageio-ffmpeg)")
    work.mkdir(parents=True, exist_ok=True)
    va, _ = pick_voices(language)
    segs = []
    for i, s in enumerate(slides):
        norm = await synth_turn(s.get("narration", s.get("title", "")), va, "A",
                                work / f"narr_{i:02d}.mp3", tts_provider, ff)
        d = max(2.0, wav_duration(norm) + 0.6)
        png = work / f"slide_{i:02d}.png"
        render_slide_png(png, f"Part {i+1}/{len(slides)}", s.get("title", ""),
                         s.get("bullets", []))
        seg = work / f"seg_{i:02d}.mp4"
        try:
            run([ff, "-y", "-loop", "1", "-framerate", "1", "-t", str(round(d, 2)), "-i", str(png),
                 "-i", str(norm), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(seg)])
        except Exception:
            run([ff, "-y", "-loop", "1", "-framerate", "1", "-t", str(round(d, 2)), "-i", str(png),
                 "-i", str(norm), "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(seg)])
        segs.append(seg)
        if prog:
            prog((i + 1) / max(1, len(slides)) * 0.9, f"rendering slide {i + 1}/{len(slides)}")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    final = work / "video.mp4"
    run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final)])
    return final

# ---------------- pptx ----------------
def build_pptx(out: Path, title: str, slides: list):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.33), Inches(7.5)
    from pptx.dml.color import RGBColor

    def _ink(shape):
        try:
            for p in shape.text_frame.paragraphs:
                for r in p.runs:
                    r.font.color.rgb = RGBColor(0x0B, 0x0B, 0x0C)
        except Exception:
            pass
    t = prs.slides.add_slide(prs.slide_layouts[0])
    t.shapes.title.text = title[:80]
    t.placeholders[1].text = f"{len(slides)} slides · generated from your sources"
    _ink(t.shapes.title)
    for s in slides:
        sl = prs.slides.add_slide(prs.slide_layouts[1])
        sl.shapes.title.text = s.get("title", "")[:80]
        _ink(sl.shapes.title)
        tf = sl.placeholders[1].text_frame
        tf.clear()
        for b in s.get("bullets", [])[:6]:
            p = tf.add_paragraph()
            p.text = b[:200]
            p.level = 0
    prs.save(str(out))
    return out

# ---------------- PDF reports (milky / ink / gold) ----------------
def _pdf_fonts(pdf):
    fam = "helvetica"
    try:
        pdf.add_font("body", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        pdf.add_font("body", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        fam = "body"
    except Exception:
        pass
    fbs = []
    for cand, name in [
        ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf", "dev"),
        ("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf", "dev"),
        ("/usr/share/fonts/truetype/fonts-indic/Lohit-Devanagari.ttf", "dev"),
    ]:
        try:
            if Path(cand).exists():
                pdf.add_font(name, "", cand)
                fbs.append(name)
        except Exception:
            pass
    if fbs:
        try:
            pdf.set_fallback_fonts(fbs)
        except Exception:
            pass
    return fam


def build_report_pdf(out: Path, title: str, md_text: str, citations: list, meta: str = ""):
    from fpdf import FPDF

    class Rep(FPDF):
        def footer(self):
            self.set_y(-15)
            self.set_font(fam, "", 8)
            self.set_text_color(130, 117, 80)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}} · NotebookLM Clone", align="C")

    pdf = Rep()
    fam = _pdf_fonts(pdf)
    pdf.alias_nb_pages("{nb}")
    pdf.set_auto_page_break(True, 22)
    pdf.add_page()
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 52, "F")
    pdf.set_y(10)
    pdf.set_x(15)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(fam, "B", 20)
    pdf.multi_cell(180, 10, (title or "Report")[:120])
    pdf.set_x(15)
    pdf.set_text_color(*GOLD)
    pdf.set_font(fam, "", 10)
    pdf.cell(180, 7, (meta or "Generated from your sources · NotebookLM Clone")[:120])
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(1.2)
    pdf.line(15, 56, 195, 56)
    pdf.set_y(62)
    for block in (md_text or "").split("\n"):
        line = block.strip()
        if not line:
            pdf.ln(3)
            continue
        pdf.set_text_color(20, 20, 22)
        if line.startswith("### "):
            pdf.set_font(fam, "B", 12)
            pdf.multi_cell(0, 7, line[4:], markdown=True)
            pdf.ln(1)
        elif line.startswith("## "):
            pdf.set_font(fam, "B", 14)
            pdf.multi_cell(0, 8, line[3:], markdown=True)
            pdf.ln(1)
        elif line.startswith("# "):
            pdf.set_font(fam, "B", 17)
            pdf.multi_cell(0, 9, line[2:], markdown=True)
            y = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.line(10, y + 1, 200, y + 1)
            pdf.ln(3)
        elif line.startswith(("- ", "* ")):
            pdf.set_font(fam, "", 11)
            pdf.set_x(15)
            pdf.set_text_color(*GOLD)
            pdf.cell(5, 6, "\u2022")
            pdf.set_text_color(20, 20, 22)
            pdf.multi_cell(0, 6, line[2:], markdown=True)
        elif re.match(r"^\d+[.)] ", line):
            m = re.match(r"^(\d+[.)]) (.*)", line)
            pdf.set_font(fam, "", 11)
            pdf.set_x(12)
            pdf.set_text_color(*GOLD)
            pdf.cell(8, 6, m.group(1))
            pdf.set_text_color(20, 20, 22)
            pdf.multi_cell(0, 6, m.group(2), markdown=True)
        else:
            pdf.set_font(fam, "", 11)
            pdf.multi_cell(0, 6, line, markdown=True)
    if citations:
        pdf.ln(4)
        pdf.set_draw_color(*GOLD)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font(fam, "B", 13)
        pdf.set_text_color(20, 20, 22)
        pdf.cell(0, 8, "Sources")
        pdf.ln(10)
        for c in citations:
            pdf.set_font(fam, "B", 10)
            pdf.set_text_color(*GOLD)
            pdf.cell(8, 6, f"[{c.get('ref', chr(8226))}]")
            pdf.set_font(fam, "", 10)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(0, 5.5, f"{c.get('source_title', '')} — {(c.get('quote', '') or '')[:300]}")
            pdf.ln(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return out


def render_mindmap_png(path: Path, root: str, nodes: list):
    from PIL import Image, ImageDraw
    nodes = nodes or []
    kids = [n for n in nodes if n.get("id") != "root"][:24]
    if not kids and nodes:
        kids = nodes[:24]
    W, H = 1080, 230 + 64 * max(len(kids), 1)
    img = Image.new("RGB", (W, H), MILK)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill=INK)
    for j, line in enumerate(textwrap.wrap(root or "Mind map", 30)[:2]):
        d.text((50, 38 + j * 52), line, font=_font(True, 46), fill=(255, 255, 255))
    d.text((50, 118), f"{len(kids)} topics", font=_font(False, 24), fill=GOLD)
    y = 190
    for i, n in enumerate(kids):
        label = n.get("label") or n.get("id") or f"Node {i + 1}"
        d.rounded_rectangle([60, y, W - 60, y + 50], radius=14, fill=(255, 255, 255), outline=(222, 211, 176), width=2)
        d.ellipse([76, y + 12, 106, y + 38], fill=GOLD)
        d.text((84, y + 13), str(i + 1), font=_font(True, 20), fill=INK)
        d.text((118, y + 13), label[:52], font=_font(False, 24), fill=(20, 20, 22))
        y += 62
    d.text((50, H - 36), "NotebookLM Clone", font=_font(False, 20), fill=(146, 124, 52))
    img.save(path)
    return path

