#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Animated MP4 render (480p) from your JSON + audio.

Fixes:
- No time-varying function passed to set_opacity (uses vfx.fadein instead).
- Delay handled with set_start(...).
- RGBA (callout/text) handled via explicit mask clips (version-friendly).

Usage:
  python video_animated.py --id test4 --root . --out out.mp4 --fps 15

Requires:
  pip install moviepy pillow requests
"""

import os, re, json, argparse, tempfile, requests
from typing import List, Tuple, Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, ColorClip
)
from moviepy.video.fx import all as vfx

# ---------- Layout / Colors ----------
W, H = 854, 480
LEFT_W  = W // 3
RIGHT_W = W - LEFT_W
PADDING = 14

BG = (0, 0, 0)
TEXT_COLOR   = (226, 232, 240)  # #e2e8f0
BULLET_COLOR = TEXT_COLOR
CALLOUT_BG   = (26, 32, 44)     # #1a202c
CALLOUT_BORDER = (66, 153, 225) # #4299e1
BOLD_COLOR   = (99, 179, 237)   # #63b3ed
ITALIC_COLOR = (250, 240, 137)  # #faf089

MAX_LINES = 4
MIN_SLIDE_SEC = 1.0
DEFAULT_FPS = 30

# ---------- Animation timings (subtle) ----------
IMG_IN_DELAY = 0.00
IMG_IN_DUR   = 0.70
IMG_SLIDE_PX = 12

CALLOUT_DELAY = 0.20
CALLOUT_DUR   = 0.35
CALLOUT_SLIDE_PX = 10

TEXT_START_DELAY = 3.5
TEXT_STAGGER     = 1.40
TEXT_DUR         = 0.60
TEXT_SLIDE_PX    = 12

# ---------- Fonts ----------
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

# ---------- Easing ----------
def ease_out_cubic(x: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, x))) ** 3

# ---------- Helpers ----------
def parse_ts(ts: str) -> float:
    ts = str(ts).replace(":", "_")
    m, s = (ts.split("_") + ["0","0"])[:2]
    return (int(m) if m.isdigit() else 0) * 60 + (int(s) if s.isdigit() else 0)

def tokenize_md(text: str):
    """Very small tokenizer for **bold** and *italic* (no nesting)."""
    text = text or ""
    runs, i = [], 0
    while i < len(text):
        if text.startswith("**", i):
            j = text.find("**", i+2)
            if j != -1: runs.append((text[i+2:j], "bold")); i = j+2; continue
        if text.startswith("*", i):
            j = text.find("*", i+1)
            if j != -1: runs.append((text[i+1:j], "italic")); i = j+1; continue
        j = i
        while j < len(text) and not text.startswith("**", j) and text[j] != "*":
            j += 1
        runs.append((text[i:j], "normal")); i = j
    return runs

def wrap_rich(draw: ImageDraw.ImageDraw, runs: List[Tuple[str,str]], fonts: dict, max_w: int):
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

def rgba_to_clip(rgba_im: Image.Image, dur: float):
    """Create an ImageClip with an alpha mask from a RGBA PIL image."""
    arr = np.array(rgba_im)
    if arr.ndim == 3 and arr.shape[2] == 4:
        rgb = arr[:, :, :3]
        a = (arr[:, :, 3].astype(float) / 255.0)
        img = ImageClip(rgb).set_duration(dur)
        mask = ImageClip(a, ismask=True).set_duration(dur)
        return img.set_mask(mask)
    else:
        return ImageClip(arr).set_duration(dur)

# ---------- Layout + rendering (PIL) ----------
def layout_right_column(draw, iw, ih, explanation, raw_lines, base_size):
    """Pick font sizes to fit height; compute vertical centering."""
    expl_size   = int(base_size * 1.00)
    lines_size  = int(base_size * 0.90)
    min_size    = 12

    while True:
        f_expl = {"normal": mkfont(FONT_REG, expl_size),
                  "bold":   mkfont(FONT_BOLD, expl_size),
                  "italic": mkfont(FONT_ITAL, expl_size)}
        f_txt  = {"normal": mkfont(FONT_REG, lines_size),
                  "bold":   mkfont(FONT_BOLD, lines_size),
                  "italic": mkfont(FONT_ITAL, lines_size)}
        lh_expl = int(expl_size * 1.3) if hasattr(f_expl["normal"], "size") else 24
        lh_txt  = int(lines_size * 1.25) if hasattr(f_txt["normal"], "size") else 20

        expl_wrapped = wrap_rich(draw, tokenize_md(explanation or ""), f_expl, iw - 20)
        expl_h = lh_expl * max(1, len(expl_wrapped)) + 16

        blocks, text_h = [], 0
        for raw in (raw_lines or [])[:MAX_LINES]:
            w = wrap_rich(draw, tokenize_md(raw or ""), f_txt, iw)
            blocks.append(w)
            text_h += lh_txt * max(1, len(w))

        total_h = expl_h + 10 + text_h
        if total_h <= ih or (expl_size <= min_size and lines_size <= min_size):
            start_y = max(0, (ih - total_h) // 2)
            return dict(
                f_expl=f_expl, f_txt=f_txt,
                lh_expl=lh_expl, lh_txt=lh_txt,
                expl_wrapped=expl_wrapped, blocks=blocks,
                expl_h=expl_h, start_y=start_y
            )
        expl_size  = max(min_size, int(expl_size * 0.94))
        lines_size = max(min_size, int(lines_size * 0.94))

def rgba_from_callout(width, height, expl_wrapped, f_expl, lh_expl):
    im = Image.new("RGBA", (width, height), (0,0,0,0))
    d  = ImageDraw.Draw(im)
    d.rectangle([0,0,width,height], fill=CALLOUT_BG + (255,))
    d.rectangle([0,0,4,height], fill=CALLOUT_BORDER + (255,))
    draw_lines(d, 10, 8, expl_wrapped, f_expl,
               {"normal": TEXT_COLOR, "bold": BOLD_COLOR, "italic": ITALIC_COLOR},
               lh_expl)
    return im

def rgba_from_textblock(width, height, block_wrapped, f_txt, lh_txt):
    im = Image.new("RGBA", (width, height), (0,0,0,0))
    d  = ImageDraw.Draw(im)
    draw_lines(d, 0, 0, block_wrapped, f_txt,
               {"normal": BULLET_COLOR, "bold": BOLD_COLOR, "italic": ITALIC_COLOR},
               lh_txt)
    return im

# ---------- Per-slide builder ----------
def build_slide_clip(slide, duration, root, pres_id, base_font_size=20):
    Rx, Ry, Rw, Rh = LEFT_W, 0, RIGHT_W, H
    ix, iy, iw, ih = Rx + PADDING, Ry + PADDING, Rw - 2*PADDING, Rh - 2*PADDING

    base = ColorClip(size=(W, H), color=BG).set_duration(duration)

    # --- Left image ---
    img_layer = None
    left_img_path = os.path.join(root, "images", pres_id, f"{slide['index']+1}.png")
    if os.path.isfile(left_img_path):
        simg = Image.open(left_img_path).convert("RGB")
        Lx, Ly, Lw, Lh = 0, 0, LEFT_W, H
        r = min(Lw / simg.width, Lh / simg.height)
        nw, nh = max(1, int(simg.width*r)), max(1, int(simg.height*r))
        simg = simg.resize((nw, nh), Image.LANCZOS)
        paste_x = Lx + (Lw - nw)//2
        paste_y = Ly + (Lh - nh)//2
        npimg = np.array(simg)
        img_layer = ImageClip(npimg).set_duration(duration)
        # gentle slide + fade-in at t=0..IMG_IN_DUR
        def img_pos(t):
            p = ease_out_cubic(t / IMG_IN_DUR) if IMG_IN_DUR > 0 else 1.0
            dx = (1 - p) * IMG_SLIDE_PX
            return (paste_x - dx, paste_y)
        img_layer = img_layer.set_position(img_pos).fx(vfx.fadein, IMG_IN_DUR)

    # --- Right column layout ---
    dummy = Image.new("RGB", (10,10))
    drw   = ImageDraw.Draw(dummy)
    right = layout_right_column(
        drw, iw, ih,
        slide["explanation"],
        (slide["slide_content"] or "").split("\n")[1:1+MAX_LINES],
        base_font_size
    )

    # Callout RGBA → clip
    call_h = right["expl_h"]
    call_rgba = rgba_from_callout(iw, call_h, right["expl_wrapped"], right["f_expl"], right["lh_expl"])
    call_clip = rgba_to_clip(call_rgba, max(0.1, duration - CALLOUT_DELAY))
    call_y = iy + right["start_y"]

    # slide-up + fade-in, starting at CALLOUT_DELAY
    def call_pos(local_t):
        p = ease_out_cubic(local_t / CALLOUT_DUR) if CALLOUT_DUR > 0 else 1.0
        dy = (1 - p) * CALLOUT_SLIDE_PX
        return (ix, call_y - dy)
    call_clip = call_clip.set_start(CALLOUT_DELAY).set_position(call_pos).fx(vfx.fadein, CALLOUT_DUR)

    # Text blocks
    text_layers = []
    cur_y = call_y + call_h + 10
    for idx, block in enumerate(right["blocks"]):
        h = right["lh_txt"] * max(1, len(block))
        tb_rgba = rgba_from_textblock(iw, h, block, right["f_txt"], right["lh_txt"])
        delay = TEXT_START_DELAY + idx * TEXT_STAGGER
        dur_remain = max(0.1, duration - delay)
        tb_clip = rgba_to_clip(tb_rgba, dur_remain)

        base_y = cur_y
        def mk_pos(by=base_y):
            def _pos(local_t):
                p = ease_out_cubic(local_t / TEXT_DUR) if TEXT_DUR > 0 else 1.0
                dy = (1 - p) * TEXT_SLIDE_PX
                return (ix, by - dy)
            return _pos

        tb_clip = tb_clip.set_start(delay).set_position(mk_pos()).fx(vfx.fadein, TEXT_DUR)
        text_layers.append(tb_clip)
        cur_y += h

    layers = [base]
    if img_layer is not None: layers.append(img_layer)
    layers.append(call_clip)
    layers.extend(text_layers)

    return CompositeVideoClip(layers, size=(W, H)).set_duration(duration)

# ---------- Timing ----------
def durations_from_timestamps(ts: List[float], audio_len: float) -> List[float]:
    out = []
    for i, t in enumerate(ts):
        d = (ts[i+1] - t) if i < len(ts)-1 else (audio_len - t)
        out.append(max(MIN_SLIDE_SEC, d))
    return out

# ---------- Audio helpers ----------
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

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Presentation Id (e.g., test4)")
    ap.add_argument("--root", default=".", help="Project root with /json, /images, /audio")
    ap.add_argument("--out",  default="out.mp4", help="Output MP4 path")
    ap.add_argument("--fps",  type=int, default=DEFAULT_FPS, help="Video FPS")
    ap.add_argument("--font_size", type=int, default=20, help="Base font size (auto-downscales)")
    args = ap.parse_args()

    json_path = os.path.join(args.root, "json", f"{args.id}.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"JSON not found: {json_path}")
    data = json.load(open(json_path, "r", encoding="utf-8"))
    entries = data.get("entries", [])
    if not entries:
        raise ValueError("No entries in JSON.")

    mp3 = data.get("mp3")
    audio_file = download_if_url(mp3) if mp3 else find_local_audio(args.root, args.id)
    if not audio_file:
        raise FileNotFoundError("No audio file found (JSON 'mp3' missing and no local /audio/<id>.*).")
    aclip = AudioFileClip(audio_file)
    alen  = float(aclip.duration)

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
    if ts and ts[0] > alen:
        raise ValueError("First slide timestamp is beyond the audio duration.")
    durs = durations_from_timestamps(ts, alen)

    clips = [build_slide_clip(s, dur, args.root, args.id, base_font_size=args.font_size)
             for s, dur in zip(slides, durs)]

    video = concatenate_videoclips(clips, method="compose")
    t0 = ts[0] if ts else 0.0
    video = video.set_audio(aclip.subclip(t_start=t0, t_end=t0 + video.duration))

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
