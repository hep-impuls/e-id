#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert an audio-driven slide JSON into a 480p MP4 video.
- Resolution: 854x480 (16:9)
- Layout: image left (1/3), text right (2/3)
- Up to 4 bullets per slide
- Slide durations from JSON timestamps; last slide runs until audio ends
- Colors roughly match your web player

Usage:
  python video.py --id test2 --root . --out out.mp4 --fps 30

Requires:
  pip install moviepy pillow requests
"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Render JSON + audio to a 480p MP4.
# Changes vs previous: (1) vertically center the whole right-column text block,
# (2) don't prepend any bullet symbol; draw the lines exactly as given.

import os, re, json, argparse, tempfile, requests
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ---------- Layout / Colors ----------
W, H = 854, 480
LEFT_W  = W // 3
RIGHT_W = W - LEFT_W
PADDING = 14

BG = (0, 0, 0)
TEXT_COLOR = (226, 232, 240)
BULLET_COLOR = TEXT_COLOR
CALLOUT_BG = (26, 32, 44)
CALLOUT_BORDER = (66, 153, 225)
BOLD_COLOR = (99, 179, 237)
ITALIC_COLOR = (250, 240, 137)

MAX_LINES = 4                 # formerly MAX_BULLETS; keep a safety cap
MIN_SLIDE_SEC = 1.0
DEFAULT_FPS = 30
XFADE = 0.0                   # keep 0 for broad MoviePy compatibility

# ---------- Fonts (adjust to Inter .ttf if you like) ----------
FONT_REG = next((p for p in [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
] if os.path.isfile(p)), None)
FONT_BOLD = next((p for p in [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
] if os.path.isfile(p)), FONT_REG)
FONT_ITAL = next((p for p in [
    "C:/Windows/Fonts/ariali.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/Library/Fonts/Arial Italic.ttf",
] if os.path.isfile(p)), FONT_REG)

def mkfont(path: Optional[str], size: int) -> ImageFont.ImageFont:
    return ImageFont.truetype(path, size) if path and os.path.isfile(path) else ImageFont.load_default()

# ---------- Helpers ----------
def parse_ts(ts: str) -> float:
    ts = str(ts).replace(":", "_")
    m, s = (ts.split("_") + ["0","0"])[:2]
    return (int(m) if m.isdigit() else 0) * 60 + (int(s) if s.isdigit() else 0)

def tokenize_md(text: str):
    """Very small tokenizer for **bold** and *italic* (no nesting)."""
    text = text or ""
    runs = []
    i = 0
    while i < len(text):
        if text.startswith("**", i):
            j = text.find("**", i+2)
            if j != -1:
                runs.append((text[i+2:j], "bold")); i = j+2; continue
        if text.startswith("*", i):
            j = text.find("*", i+1)
            if j != -1:
                runs.append((text[i+1:j], "italic")); i = j+1; continue
        j = i
        while j < len(text) and not text.startswith("**", j) and text[j] != "*":
            j += 1
        runs.append((text[i:j], "normal")); i = j
    return runs

def wrap_rich(draw: ImageDraw.ImageDraw, runs: List[Tuple[str,str]], fonts: dict, max_w: int):
    """Word-wrap rich runs into lines that fit max_w."""
    lines, cur, cur_w = [], [], 0
    def seg_w(t, st): 
        try: return draw.textlength(t, font=fonts[st])
        except Exception: return len(t) * fonts["normal"].size * 0.6
    for txt, st in runs:
        for tok in re.findall(r"\S+|\s+", txt):
            w = seg_w(tok, st)
            if cur_w + w <= max_w or (tok.isspace() and not cur):
                cur.append((tok, st)); cur_w += w
            else:
                lines.append(cur); cur = [(tok, st)]; cur_w = seg_w(tok, st)
    if cur: lines.append(cur)
    return lines

def draw_lines(draw, x, y, lines, fonts, fills, line_h):
    for line in lines:
        cx = x
        for t, st in line:
            draw.text((cx, y), t, font=fonts[st], fill=fills.get(st, TEXT_COLOR))
            try: cx += draw.textlength(t, font=fonts[st])
            except Exception: cx += len(t) * fonts["normal"].size * 0.6
        y += line_h
    return y

def download_if_url(path_or_url: str) -> str:
    if re.match(r'^https?://', str(path_or_url), re.I):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(path_or_url)[1] or ".bin"); tmp.close()
        with requests.get(path_or_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(tmp.name, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk: f.write(chunk)
        return tmp.name
    return path_or_url

def find_local_audio(root: str, pres_id: str) -> Optional[str]:
    base = os.path.join(root, "audio", pres_id)
    for ext in (".mp3", ".m4a", ".wav", ".mp4"):
        p = base + ext
        if os.path.isfile(p): return p
    return None

# ---------- Slide rendering ----------
def render_slide_image(canvas_w: int, canvas_h: int, left_img_path: Optional[str],
                       explanation: str, lines_right: List[str], base_size: int = 20) -> Image.Image:
    """
    Build a PIL image for one slide.
    RIGHT COLUMN: callout + given lines (no extra bullets), block vertically centered.
    """
    img = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    # Left (image) — center inside its box
    Lx, Ly, Lw, Lh = 0, 0, LEFT_W, H
    if left_img_path and os.path.isfile(left_img_path):
        try:
            simg = Image.open(left_img_path).convert("RGB")
            r = min(Lw / simg.width, Lh / simg.height)
            nw, nh = max(1, int(simg.width * r)), max(1, int(simg.height * r))
            simg = simg.resize((nw, nh), Image.LANCZOS)
            img.paste(simg, (Lx + (Lw-nw)//2, Ly + (Lh-nh)//2))
        except Exception:
            pass

    # Right (text)
    Rx, Ry, Rw, Rh = LEFT_W, 0, RIGHT_W, H
    ix, iy, iw, ih = Rx + PADDING, Ry + PADDING, Rw - 2*PADDING, Rh - 2*PADDING

    # Auto-downscale fonts to make content fit height
    expl_size   = int(base_size * 1.00)
    lines_size  = int(base_size * 0.90)
    min_size    = 12

    while True:
        f_expl = {
            "normal": mkfont(FONT_REG, expl_size),
            "bold":   mkfont(FONT_BOLD, expl_size),
            "italic": mkfont(FONT_ITAL, expl_size),
        }
        f_txt = {
            "normal": mkfont(FONT_REG, lines_size),
            "bold":   mkfont(FONT_BOLD, lines_size),
            "italic": mkfont(FONT_ITAL, lines_size),
        }
        lh_expl = int(expl_size * 1.3) if hasattr(f_expl["normal"], "size") else 24
        lh_txt  = int(lines_size * 1.25) if hasattr(f_txt["normal"], "size") else 20

        # wrap explanation (inside callout, with 10px inner padding -> iw-20)
        expl_lines = wrap_rich(draw, tokenize_md(explanation or ""), f_expl, iw - 20)
        expl_h = lh_expl * max(1, len(expl_lines)) + 16  # padding in callout

        # wrap "lines_right" (verbatim – no added bullet symbol)
        wr_lines = []
        text_h = 0
        for raw in (lines_right or [])[:MAX_LINES]:
            runs = tokenize_md(raw or "")      # keep "- " as provided
            ls = wrap_rich(draw, runs, f_txt, iw)
            wr_lines.append(ls)
            text_h += lh_txt * max(1, len(ls))

        total_h = expl_h + 10 + text_h
        if total_h <= ih or (expl_size <= min_size and lines_size <= min_size):
            break
        expl_size  = max(min_size, int(expl_size * 0.94))
        lines_size = max(min_size, int(lines_size * 0.94))

    # Rebuild final fonts (sizes may have changed)
    f_expl = {
        "normal": mkfont(FONT_REG, expl_size),
        "bold":   mkfont(FONT_BOLD, expl_size),
        "italic": mkfont(FONT_ITAL, expl_size),
    }
    f_txt = {
        "normal": mkfont(FONT_REG, lines_size),
        "bold":   mkfont(FONT_BOLD, lines_size),
        "italic": mkfont(FONT_ITAL, lines_size),
    }
    lh_expl = int(expl_size * 1.3) if hasattr(f_expl["normal"], "size") else 24
    lh_txt  = int(lines_size * 1.25) if hasattr(f_txt["normal"], "size") else 20

    # --- Vertical centering of the whole block (callout + lines) ---
    expl_lines = wrap_rich(draw, tokenize_md(explanation or ""), f_expl, iw - 20)
    # re-measure text block height using final fonts
    text_h = 0
    wr_lines = []
    for raw in (lines_right or [])[:MAX_LINES]:
        ls = wrap_rich(draw, tokenize_md(raw or ""), f_txt, iw)
        wr_lines.append(ls)
        text_h += lh_txt * max(1, len(ls))
    block_h = (lh_expl * max(1, len(expl_lines)) + 16) + 10 + text_h
    start_y = iy + max(0, (ih - block_h) // 2)

    # --- Draw callout ---
    call_x, call_y, call_w = ix, start_y, iw
    call_h = lh_expl * max(1, len(expl_lines)) + 16
    ImageDraw.Draw(img).rectangle([call_x, call_y, call_x+call_w, call_y+call_h], fill=CALLOUT_BG)
    ImageDraw.Draw(img).rectangle([call_x, call_y, call_x+4,     call_y+call_h], fill=CALLOUT_BORDER)
    draw = ImageDraw.Draw(img)  # refresh
    draw_lines(draw, call_x+10, call_y+8, expl_lines, f_expl,
               {"normal": TEXT_COLOR, "bold": BOLD_COLOR, "italic": ITALIC_COLOR},
               lh_expl)

    # --- Draw the lines (verbatim) below callout ---
    cur_y = call_y + call_h + 10
    for para in wr_lines:
        cur_y = draw_lines(draw, ix, cur_y, para, f_txt,
                           {"normal": BULLET_COLOR, "bold": BOLD_COLOR, "italic": ITALIC_COLOR},
                           lh_txt)
    return img

# ---------- Timing / assembly ----------
def durations_from_timestamps(ts: List[float], audio_len: float) -> List[float]:
    out = []
    for i, t in enumerate(ts):
        d = (ts[i+1] - t) if i < len(ts)-1 else (audio_len - t)
        out.append(max(MIN_SLIDE_SEC, d))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out",  default="out.mp4")
    ap.add_argument("--fps",  type=int, default=DEFAULT_FPS)
    ap.add_argument("--font_size", type=int, default=20)
    args = ap.parse_args()

    json_path = os.path.join(args.root, "json", f"{args.id}.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"JSON not found: {json_path}")

    data = json.load(open(json_path, "r", encoding="utf-8"))
    entries = data.get("entries", [])
    if not entries:
        raise ValueError("No entries in JSON.")

    # audio
    mp3 = data.get("mp3")
    audio_file = download_if_url(mp3) if mp3 else find_local_audio(args.root, args.id)
    if not audio_file:
        raise FileNotFoundError("No audio file found (JSON 'mp3' missing and no local /audio/<id>.*).")
    aclip = AudioFileClip(audio_file)
    alen  = float(aclip.duration)

    # slides
    slides = []
    for i, e in enumerate(entries):
        slides.append({
            "index": i,
            "timestamp": parse_ts(e.get("timestamp", "0_00")),
            "explanation": e.get("explanation", ""),
            "slide_content": e.get("slide_content", "")
        })
    slides.sort(key=lambda s: s["timestamp"])
    ts = [s["timestamp"] for s in slides]
    durs = durations_from_timestamps(ts, alen)

    # render frames
    tmpdir = tempfile.mkdtemp(prefix=f"slides_{args.id}_")
    frames = []
    for s in slides:
        left_img = os.path.join(args.root, "images", args.id, f"{s['index']+1}.png")
        # lines on the right are everything after the first line (Title), verbatim:
        raw_lines = (s["slide_content"] or "").split("\n")[1:1+MAX_LINES]
        frame = render_slide_image(W, H, left_img, s["explanation"], raw_lines, base_size=args.font_size)
        p = os.path.join(tmpdir, f"slide_{s['index']:03d}.png")
        frame.save(p, "PNG"); frames.append(p)

    # build video
    clips = [ImageClip(p).set_duration(d).set_fps(args.fps) for p, d in zip(frames, durs)]
    video = concatenate_videoclips(clips, method="compose")

    # audio from first timestamp to end
    t0 = ts[0] if ts else 0.0
    video = video.set_audio(aclip.subclip(t_start=t0, t_end=alen))

    print(f"Writing {args.out} ...")
    video.write_videofile(
        args.out,
        fps=args.fps,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        preset="medium",
        threads=4
    )
    print("Done.")

if __name__ == "__main__":
    main()
