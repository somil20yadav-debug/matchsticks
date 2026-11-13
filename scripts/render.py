"""SCENES.tsv + WORDS.tsv + audio -> the finished stickman explainer (still pictures, hard cuts)

Run it from the project folder:
    python <skill>/scripts/render.py                 # mix.wav if present, else VO.wav
    python <skill>/scripts/render.py --audio VO.wav --out draft.mp4
    python <skill>/scripts/render.py --selfcheck     # renders a test card (Latin + Hindi) and exits

SCENES.tsv (tab separated, '#' lines ignored, header 'cue img text pos extra'):
  cue    line.word from WORDS.tsv (07.0 = line 07, word 0). The scene starts on that spoken word.
  img    picture path in the project (img/s07.jpg), or "card" for a plain text card
  text   words drawn in code. "|" = new line. Leave EMPTY on most pictures (PLAYBOOK rule 6)
  pos    leave empty: the tag goes to the quietest corner so it never covers a face.
         Force a spot only if needed: top! tl! tr! bottom! bl! br!
  extra  optional bar chart: bars:RAW=51,COOKED=91 (values in %, drawn on a card at the right)

Hybrid look (stills + cut-out stickers, PLAYBOOK section 9): a row whose cue starts with "+" adds
an overlay to the scene above it, popping in on that spoken word:
  +cue   line.word when it appears (inside the scene)
  img    elements/cut/NN.png | count (an animated number) | tag (a plain sticky-note tag)
  text   label under the sticker; for count: "14000|YEARS OLD" (number|caption); for tag: the words
  pos    auto[,h] (default auto,0.42): the quietest free spot of the picture, so a sticker never covers
         a face; or x,y,h = centre x, centre y and height as fractions of the frame (0.72,0.55,0.45)
  extra  pop (default) | slideL | slideR | rise; add +plain for no white sticker border ("no" signs). (+x draws a code strike-out; a reviewer disliked it.
         For "no fridge, no fire" generate the sticker WITH a red no-sign instead, PLAYBOOK §9.)
With overlay rows the film is rendered frame by frame (30 fps); without them, as plain stills.

The look (text card colours) comes from the first line of STYLE.txt ("look: bright"),
or --look. Pictures: img/clean/<name>.png (LaMa, from delama.py) is used when present.
Fonts: Patrick Hand for Latin text, Kalam for Devanagari and other scripts;
complex scripts go through libass (ffmpeg) because Pillow alone breaks Hindi conjuncts.
Override with STICK_FONT / STICK_FONT_COMPLEX (a .ttf path).
"""
import argparse, csv, os, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), "fonts")
FONT = os.environ.get("STICK_FONT", os.path.join(FONTS, "PatrickHand-Regular.ttf"))
FONT_CX = os.environ.get("STICK_FONT_COMPLEX", os.path.join(FONTS, "Kalam-Bold.ttf"))

# label tag colour, ink, text card centre -> edge. One per look in looks/*.md
LOOKS = {"warm":    ((252, 244, 222), (58, 34, 18), (236, 190, 105), (196, 132, 58)),
         "bright":  ((255, 253, 246), (28, 32, 44), (252, 249, 238), (196, 222, 240)),
         "ink":     ((255, 255, 255), (20, 20, 20), (252, 251, 247), (232, 229, 220)),
         "painted": ((246, 243, 236), (34, 36, 40), (226, 226, 222), (150, 158, 160)),
         "night":   ((250, 242, 220), (24, 20, 30), (58, 62, 84), (18, 20, 32))}
PAPER, INK, CARD_IN, CARD_OUT = LOOKS["warm"]
CARD_INK = INK


def set_look(name):
    global PAPER, INK, CARD_IN, CARD_OUT, CARD_INK
    PAPER, INK, CARD_IN, CARD_OUT = LOOKS[name]
    CARD_INK = PAPER if name == "night" else INK       # light words on the dark card


_cards = {}


def card():
    """Text card: soft radial vignette and faint paper grain (made once per look, float32 to spare RAM)."""
    if (CARD_IN, CARD_OUT) not in _cards:
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.clip(np.hypot((x - W / 2) / (W * 0.62), (y - H / 2) / (H * 0.62)), 0, 1)[..., None]
        a = np.array(CARD_IN, np.float32) * (1 - r) + np.array(CARD_OUT, np.float32) * r
        a += np.random.default_rng(7).normal(0, 3.5, a.shape[:2]).astype(np.float32)[..., None]
        _cards[(CARD_IN, CARD_OUT)] = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    return _cards[(CARD_IN, CARD_OUT)].copy()


def unmark(im):
    """Fill Flow's Gemini sparkle (fixed ~58 px box inset from bottom-right of 1376x768) by harmonic fill."""
    a = np.asarray(im.convert("RGB"), np.float32).copy()
    h, w = a.shape[:2]
    if w < 400 or h < 300:
        return im.convert("RGB")
    x0, y0 = w - 126, h - 126
    x1, y1, pad = x0 + 62, y0 + 62, 6
    reg = a[y0 - pad:y1 + pad, x0 - pad:x1 + pad]
    m = np.zeros(reg.shape[:2], bool)
    m[pad:-pad, pad:-pad] = True
    reg[m] = reg[~m].mean(axis=0)
    for _ in range(400):                           # Laplace relaxation: sky, walls and paper blend invisibly
        avg = (np.roll(reg, 1, 0) + np.roll(reg, -1, 0) + np.roll(reg, 1, 1) + np.roll(reg, -1, 1)) / 4
        reg[m] = avg[m]
    a[y0 - pad:y1 + pad, x0 - pad:x1 + pad] = reg
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def fit(im):
    """Cover 1920x1080, keep the centre."""
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((l, t, l + W, t + H))


FLIP = set()


def picture(path):
    """A scene picture, sparkle-free: img/clean/<name>.png from delama.py (LaMa) if it exists,
    else the Flow file with the smooth fill."""
    clean = os.path.join(os.path.dirname(path), "clean", os.path.splitext(os.path.basename(path))[0] + ".png")
    if os.path.exists(clean) and os.path.getmtime(clean) >= os.path.getmtime(path):
        im = fit(Image.open(clean).convert("RGB"))
    else:
        im = fit(unmark(Image.open(path)))
    if os.path.splitext(os.path.basename(path))[0] in FLIP:      # mirrored after the mark is gone
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    return im


# ------------------------------------------------------------------ text
_TMP, _cache = None, {}


def complex_script(s):
    """Scripts that need shaping (Hebrew, Arabic, Indic, Thai, ... and CJK). Symbols such as ≈ · — stay Latin."""
    return any(0x0590 <= ord(c) < 0x2000 or ord(c) >= 0x3000 for c in s)


def libass_mask(text, size):
    """White-on-black render of one line through libass with complex shaping -> L mask, tight crop."""
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix="stick_")
        shutil.copy(FONT_CX, os.path.join(_TMP, "cx.ttf"))
    family = ImageFont.truetype(FONT_CX, 20).getname()[0]
    clean = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    cw, ch = int(size * max(4, len(text)) * 0.9), int(size * 3)
    open(os.path.join(_TMP, "t.ass"), "w", encoding="utf-8").write(
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {cw}\nPlayResY: {ch}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: T,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:05.00,T,,0,0,0,,{clean}\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={cw}x{ch}",
                    "-vf", "ass=t.ass:fontsdir=.:shaping=complex", "-frames:v", "1", "t.png"],
                   cwd=_TMP, check=True)
    m = Image.open(os.path.join(_TMP, "t.png")).convert("L")
    return m.crop(m.getbbox() or (0, 0, 1, 1))


def text_layer(text, size, colour):
    """One line of text as a tight RGBA image. Latin -> Pillow; Hindi and other scripts -> libass."""
    key = (text, size, colour)
    if key not in _cache:
        if complex_script(text):
            m = libass_mask(text, size)
            want = ImageFont.truetype(FONT_CX, size).getbbox(text)
            th = max(1, want[3] - want[1])                   # match the Latin line height
            m = m.resize((max(1, round(m.width * th / m.height)), th), Image.LANCZOS)
        else:
            f = ImageFont.truetype(FONT, size)
            b = f.getbbox(text)
            m = Image.new("L", (b[2] - b[0] + 4, b[3] - b[1] + 4), 0)
            ImageDraw.Draw(m).text((2 - b[0], 2 - b[1]), text, font=f, fill=255)
        im = Image.new("RGBA", m.size, colour + (0,))
        im.putalpha(m)
        _cache[key] = im
    return _cache[key]


SPOTS = ["top", "tl", "tr", "bottom", "bl", "br"]       # auto tries these, in order of preference


def busy(fr):
    """Edge strength at 1/8 size: faces, bodies and props are busy; sky and walls are quiet."""
    g = np.asarray(fr.convert("L").resize((W // 8, H // 8)), np.float32)
    return np.abs(np.diff(g, axis=0, prepend=g[:1])) + np.abs(np.diff(g, axis=1, prepend=g[:, :1]))


def label(fr, text, pos, blocked=()):
    """pos: big (card) | auto (the quietest corner, so a tag never covers a face) | spot! (forced)."""
    big = pos == "big"
    size = 140 if big else 70
    colour = CARD_INK if big else INK
    lines = [text_layer(ln, size, colour) for ln in text.split("|")]
    gap = int(size * 0.28)
    tw = max(l.width for l in lines)
    th = sum(l.height for l in lines) + gap * (len(lines) - 1)

    def centre(p):
        if p == "big":
            return W // 2, H // 2
        cx = {"tl": 80 + tw // 2, "bl": 80 + tw // 2, "tr": W - 80 - tw // 2, "br": W - 80 - tw // 2}.get(p, W // 2)
        cy = {"top": 70 + th // 2, "tl": 70 + th // 2, "tr": 70 + th // 2}.get(p, H - 80 - th // 2)
        return cx, cy

    def rect(p):
        cx, cy = centre(p)
        return (cx - tw // 2 - 34, cy - th // 2 - 22, cx + tw // 2 + 34, cy + th // 2 + 22)

    if pos.endswith("!"):
        pos = pos[:-1]
    elif not big:
        e = busy(fr)

        def cost(i, p):
            x0, y0, x1, y1 = rect(p)
            if any(x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1 for bx0, by0, bx1, by1 in blocked):
                return 1e9
            pad = 40                                       # count what sits just around the tag too
            m = e[max(0, (y0 - pad) // 8):(y1 + pad) // 8, max(0, (x0 - pad) // 8):(x1 + pad) // 8]
            return float(m.mean()) * (1 + 0.04 * i)
        pos = min(SPOTS, key=lambda p: cost(SPOTS.index(p), p))
    cx, cy = centre(pos)
    if not big:                                            # paper tag behind the words
        ImageDraw.Draw(fr).rounded_rectangle(rect(pos), radius=18, fill=PAPER, outline=INK, width=4)
    y = cy - th // 2
    for l in lines:
        fr.paste(l, (cx - l.width // 2, y), l)
        y += l.height + gap


CHART = (1300, 250, 1860, 1010)


def bars(fr, spec):
    """bars:NAME=pct,NAME=pct  -> a small bar chart card on the right."""
    items = [kv.split("=") for kv in spec.split(",")]
    d = ImageDraw.Draw(fr)
    d.rounded_rectangle(CHART, radius=28, fill=PAPER, outline=INK, width=5)
    n = len(items)
    bw = min(170, (CHART[2] - CHART[0] - 80) // n - 40)
    x, base, maxh = CHART[0] + 50, 920, 520
    for i, (name, val) in enumerate(items):
        x0 = x + i * (bw + 50)
        top = base - maxh * float(val) / 100
        d.rectangle((x0, top, x0 + bw, base), fill=(230, 120, 60) if i == n - 1 else (170, 170, 170),
                    outline=INK, width=5)
        for t, yy, sz in ((f"{val}%", top - 76, 64), (name, base + 16, 50)):
            l = text_layer(t, sz, INK)
            fr.paste(l, (int(x0 + bw / 2 - l.width / 2), int(yy)), l)
    d.line((x - 30, base, x + n * (bw + 50), base), fill=INK, width=5)


# ------------------------------------------------------------------ hybrid (stickers on scenes)
FPS = 30
_stickers = {}
SPACE = {}
FLIP = set()


def sticker(path, h, plain=False):
    """Cut-out PNG at height h px, with a white sticker border and a soft shadow (collage feel).
    plain=True: no white border, only the soft shadow (for "no" signs, which look odd with one)."""
    key = (path, h, plain)
    if key not in _stickers:
        if len(_stickers) > 24:                      # sizes tried while separating are not needed again
            _stickers.clear()
        from PIL import ImageFilter
        im = Image.open(path).convert("RGBA")
        im = im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)
        b = max(6, h // 45)
        pad = b * 4
        big = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
        big.paste(im, (pad, pad), im)
        ring = big.getchannel("A").filter(ImageFilter.MaxFilter(2 * b + 1))
        shadow = Image.new("RGBA", big.size, (0, 0, 0, 0))
        shadow.putalpha(ring.point(lambda v: int(v * 0.35)).filter(ImageFilter.GaussianBlur(b * 1.5)))
        out = Image.new("RGBA", big.size, (0, 0, 0, 0))
        out.alpha_composite(shadow, (b // 2, b))
        if not plain:
            white = Image.new("RGBA", big.size, (255, 255, 255, 0))
            white.putalpha(ring)
            out.alpha_composite(white)
        out.alpha_composite(big)
        _stickers[key] = out
    return _stickers[key]


def tag_image(text, size=80):
    """A sticky-note tag as RGBA (paper fill, ink outline), for overlays."""
    lines = [text_layer(ln, size, INK) for ln in text.split("|")]
    gap = int(size * 0.25)
    tw = max(l.width for l in lines) + 60
    th = sum(l.height for l in lines) + gap * (len(lines) - 1) + 40
    im = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((4, 4, tw + 4, th + 4), radius=16, fill=PAPER + (255,),
                                         outline=INK, width=4)
    y = 24
    for l in lines:
        im.alpha_composite(l, ((im.width - l.width) // 2, y))
        y += l.height + gap
    return im


def ease_back(p):
    c = 1.7
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def place(fr, im, cx, cy, p, motion):
    """Draw im centred at (cx, cy) at animation progress p (0..1)."""
    if p <= 0:
        return
    alpha = min(1.0, p / 0.35)
    q = ease_back(min(1.0, p))
    if motion == "pop":
        sc = 0.55 + 0.45 * q
        if abs(sc - 1) > 1e-3:
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR)
    elif motion == "slideL":
        cx -= (1 - q) * W * 0.35
    elif motion == "slideR":
        cx += (1 - q) * W * 0.35
    elif motion == "rise":
        cy += (1 - q) * H * 0.25
    if alpha < 1:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    fr.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def pacing(events, total, out):
    """Every cut and every overlay is a visual change. Report holds that are too long:
    over 2.0 s in the first 30 s (the hook), over 3.5 s after it."""
    ev = sorted(set(round(t, 2) for t in events if 0 <= t < total)) + [total]
    holds = []
    for a, b in zip(ev, ev[1:]):
        limit = 2.0 if a < 30 else 3.5
        if b - a > limit:
            holds.append((a, b))
    gaps = [b - a for a, b in zip(ev, ev[1:])]
    print(f"pacing: {len(ev) - 1} visual changes, one every {total / max(1, len(ev) - 1):.2f}s on average; "
          f"hook (0-30s): {sum(1 for t in ev if t < 30)} changes")
    if holds:
        print("LONG HOLDS (add a cut, a sticker, a counter or a card on a word in these spans):")
        for a, b in holds:
            print(f"  {a:6.1f}s - {b:6.1f}s  ({b - a:.1f}s)")
    else:
        print("no long holds")


def cross_layer(w, h, k):
    """A sticker-style strike-out: two slightly tilted strokes with round ends, coral-red fill, dark ink
    outline and a white sticker border. k (0..1) draws stroke 1 in the first half, stroke 2 in the second."""
    S = 3                                                    # draw large, scale down for smooth edges
    W2, H2 = int(w * 0.78) * S, int(h * 0.78) * S
    lw = max(8, min(w, h) // 11) * S
    pad = lw * 2
    im = Image.new("RGBA", (W2 + 2 * pad, H2 + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    strokes = [((pad + W2 * 0.06, pad + H2 * 0.02), (pad + W2 * 0.94, pad + H2 * 0.96)),
               ((pad + W2 * 0.92, pad + H2 * 0.04), (pad + W2 * 0.08, pad + H2 * 0.98))]
    parts = []
    for n, (a, b) in enumerate(strokes):
        f = max(0.0, min(1.0, k * 2 - n))
        if f > 0:
            parts.append((a, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)))
    for width, colour in ((lw + 10 * S, (255, 255, 255, 255)), (lw + 4 * S, (40, 34, 40, 255)), (lw, (232, 72, 60, 255))):
        for a, b in parts:
            d.line((a, b), fill=colour, width=width)
            for x, y in (a, b):
                r = width / 2
                d.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    return im.resize((im.width // S, im.height // S), Image.LANCZOS)


def render_motion(rows, words, total, audio, out):
    global SPACE
    SPACE = {}
    FLIP.clear()
    if os.path.exists("SHOTS.tsv"):                # sNN -> the side the picture keeps empty
        for r in csv.DictReader(open("SHOTS.tsv", encoding="utf-8"), delimiter="	"):
            if (r.get("space") or "").strip().lower() in ("left", "right", "top"):
                SPACE[f"s{int(r['id']):02d}"] = r["space"].strip().lower()
            if (r.get("flip") or "").strip().lower() in ("yes", "y", "1", "true"):
                FLIP.add(f"s{int(r['id']):02d}")
    scenes = []
    for r in rows:
        r += [""] * (5 - len(r))
        cue = r[0].strip()
        if cue.startswith("+"):
            c = cue[1:]
            if c not in words:
                sys.exit(f"overlay cue {c} is not a line.word in WORDS.tsv")
            if not scenes:
                sys.exit("an overlay row needs a scene row above it")
            pos = r[3].strip() or "auto"
            if pos.startswith("auto"):
                x, y, h = None, None, min(0.34, float(pos.split(",")[1]) if "," in pos else 0.3)
            else:
                x, y, h = (float(v) for v in pos.split(","))
            mo = r[4].strip() or "pop"
            plain = "plain" in mo
            mo = mo.replace("+plain", "").replace("plain", "").strip("+,") or "pop"
            scenes[-1]["ov"].append(dict(t=words[c] - 0.05, img=r[1].strip(), text=r[2].strip(),
                                         x=x, y=y, h=h, motion=mo.replace("+x", "") or "pop", cross="+x" in mo,
                                         plain=plain))
        else:
            if cue not in words:
                sys.exit(f"cue {cue} is not a line.word in WORDS.tsv")
            scenes.append(dict(t0=words[cue] if scenes else 0.0, row=r, ov=[]))
    for a, b in zip(scenes, scenes[1:]):
        a["t1"] = b["t0"]
    scenes[-1]["t1"] = total
    bad = [i + 1 for i in range(1, len(scenes)) if scenes[i]["t0"] <= scenes[i - 1]["t0"]]
    if bad:
        sys.exit(f"scene {bad[0]} does not come after the one before it")
    for sc in scenes:
        for o in sc["ov"]:
            if not sc["t0"] - 0.1 <= o["t"] < sc["t1"]:
                sys.exit(f"overlay {o['img']} {o['text']!r} at {o['t']:.2f}s falls outside its scene")
    def autoplace(sc):
        """Give every 'auto' overlay the quietest free spot of its scene picture."""
        todo = [o for o in sc["ov"] if o["x"] is None]
        if not todo:
            return
        img = sc["row"][1].strip()
        pic = card() if img == "card" else picture(img)
        e = busy(pic)
        side = SPACE.get(os.path.splitext(os.path.basename(img))[0])
        if img != "card":
            # stickman heads and bodies are big flat white shapes: no edges inside, so the edge map
            # calls them "quiet". Count near-white, unsaturated pixels as busy too.
            a = np.asarray(pic.resize((W // 8, H // 8)), np.int16)
            white = (a.min(axis=2) > 232) & (a.max(axis=2) - a.min(axis=2) < 14)
            r, g, b = a[..., 0], a[..., 1], a[..., 2]          # beige / brown cartoon faces and arms
            skin = (r > 185) & (g > 140) & (b > 100) & (r > g) & (g > b) & (r - b > 35) & (r - b < 105)
            e = e + white * 60.0 + skin * 40.0
        taken = [(o["x"], o["y"], o["h"]) for o in sc["ov"] if o["x"] is not None]
        spots = [(0.86, 0.2), (0.14, 0.2), (0.86, 0.78), (0.14, 0.78), (0.5, 0.16),
                 (0.76, 0.3), (0.24, 0.3), (0.78, 0.62), (0.22, 0.62), (0.5, 0.84)]
        if side == "top":                         # the picture was composed with the sky left empty
            spots = [(0.3, 0.2), (0.7, 0.2), (0.5, 0.17), (0.16, 0.2), (0.84, 0.2)]
        elif side:                                # the picture was composed with this side left empty
            xs = (0.8, 0.86) if side == "right" else (0.2, 0.14)
            spots = [(xs[0], 0.3), (xs[0], 0.62), (xs[1], 0.18), (xs[1], 0.8), (xs[0], 0.46)]
        for o in todo:
            hh = o["h"] * H
            ww = hh * 1.1

            def cost(i, xy):
                x0, y0 = xy[0] * W - ww / 2, xy[1] * H - hh / 2
                for tx, ty, th in taken:                       # do not stack stickers on each other
                    if abs(tx - xy[0]) * W < (ww + th * H * 1.1) / 2 and abs(ty - xy[1]) * H < (hh + th * H) / 2:
                        return 1e9
                m = e[max(0, int(y0) // 8):int(y0 + hh) // 8, max(0, int(x0) // 8):int(x0 + ww) // 8]
                centre = 1 + 1.2 * np.exp(-((xy[0] - 0.5) ** 2 / 0.05 + (xy[1] - 0.55) ** 2 / 0.08))  # main element
                return float(m.mean()) * centre * (1 + 0.03 * i) if m.size else 1e9
            o["x"], o["y"] = min(spots, key=lambda xy: cost(spots.index(xy), xy))
            taken.append((o["x"], o["y"], o["h"]))

    def extent(o):
        """Real on-screen box (w, h, dy) of an overlay: sticker plus its label tag below it."""
        hh = int(o["h"] * H)
        if o["img"] == "count":
            num, _, cap = o["text"].partition("|")
            im = tag_image(f"{float(num.replace(',', '')):,.0f}" + (f"|{cap}" if cap else ""), max(50, hh // 4))
            return im.width, im.height, 0
        if o["img"] == "tag":
            im = tag_image(o["text"], max(46, hh // 4))
            return im.width, im.height, 0
        st = sticker(o["img"], hh, o.get("plain", False))
        if not o["text"]:
            return st.width, st.height, 0
        tg = tag_image(o["text"], 60)
        w, h = max(st.width, tg.width), st.height + tg.height - 10
        return w, h, (tg.height - 10) / 2               # the box centre sits below the sticker centre

    def separate(sc):
        """Push overlays of one scene apart so no two touch (a 24 px gap), shrinking if they cannot fit."""
        ov = sc["ov"]
        for _ in range(12):
            boxes = []
            for o in ov:
                w, h, dy = extent(o)
                boxes.append([o["x"] * W, o["y"] * H + dy, w, h])
            moved = False
            for i in range(len(ov)):
                for j in range(i + 1, len(ov)):
                    a, b = boxes[i], boxes[j]
                    need_x = (a[2] + b[2]) / 2 + 24 - abs(a[0] - b[0])
                    need_y = (a[3] + b[3]) / 2 + 24 - abs(a[1] - b[1])
                    if need_x > 0 and need_y > 0:
                        moved = True
                        sgn = 1 if b[0] >= a[0] else -1
                        ov[i]["x"] -= sgn * need_x / 2 / W
                        ov[j]["x"] += sgn * need_x / 2 / W
            for o, bx in zip(ov, boxes):              # keep everything inside the frame
                half = bx[2] / 2 / W
                o["x"] = min(max(o["x"], half + 0.02), 1 - half - 0.02)
            if not moved:
                return
            for o in ov:                               # still colliding next round: shrink a little
                o["h"] *= 0.94

    for sc in scenes:
        autoplace(sc)
        separate(sc)
    cache = {}

    def base(sc):
        k = id(sc)
        if k not in cache:
            _, img, text, pos, extra = [x.strip() for x in sc["row"][:5]]
            fr = card() if img == "card" else picture(img)
            blocked = []
            if extra.startswith("bars:"):
                bars(fr, extra[5:])
                blocked.append(CHART)
            for o in sc["ov"]:                     # keep the scene tag off where stickers land
                hh = o["h"] * H
                ww = hh * 1.2
                blocked.append((o["x"] * W - ww / 2, o["y"] * H - hh / 2, o["x"] * W + ww / 2, o["y"] * H + hh / 2))
            if text:
                label(fr, text, "big" if img == "card" else (pos if pos.endswith("!") else "auto"), blocked)
            cache.clear()
            cache[k] = fr.convert("RGBA")
        return cache[k]

    os.makedirs("frames", exist_ok=True)
    for f in os.listdir("frames"):
        if f.endswith(".png"):
            os.remove(os.path.join("frames", f))
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "medium",
                           "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "3", "-c:a", "aac", "-b:a", "192k",
                           "-shortest", out], stdin=subprocess.PIPE)
    si, last_key, last = 0, None, None
    for fi in range(int(total * FPS) + 1):
        t = fi / FPS
        while si + 1 < len(scenes) and t >= scenes[si + 1]["t0"]:
            Image.frombytes("RGB", (W, H), last).save(f"frames/{si + 1:03d}.png")   # QC: last frame of scene
            si += 1
        sc = scenes[si]
        prog = [min(1.0, max(0.0, (t - o["t"]) / 0.4)) for o in sc["ov"]]
        counting = any((o["img"] == "count" and 0 < t - o["t"] < 0.95) or
                       (o.get("cross") and 0.25 < t - o["t"] < 0.65) for o in sc["ov"])
        key = (si, tuple(round(p, 3) for p in prog), round(t, 3) if counting else 0)
        if key != last_key:
            fr = base(sc).copy()
            for o, p in zip(sc["ov"], prog):
                if p <= 0:
                    continue
                cx, cy, hh = o["x"] * W, o["y"] * H, int(o["h"] * H)
                if o["img"] == "count":
                    num, _, cap = o["text"].partition("|")
                    target = float(num.replace(",", ""))
                    v = target * (1 - (1 - min(1.0, (t - o["t"]) / 0.9)) ** 3)
                    s_num = f"{int(round(v)):,}" if target >= 1000 else str(int(round(v)))
                    place(fr, tag_image(s_num + (f"|{cap}" if cap else ""), max(50, hh // 4)), cx, cy, p, o["motion"])
                elif o["img"] == "tag":
                    place(fr, tag_image(o["text"], max(46, hh // 4)), cx, cy, p, o["motion"])
                else:
                    st = sticker(o["img"], hh, o.get("plain", False))
                    place(fr, st, cx, cy, p, o["motion"])
                    if o.get("cross") and t - o["t"] > 0.3:       # strike it out: "no fridge"
                        k = min(1.0, (t - o["t"] - 0.3) / 0.3)
                        cr = cross_layer(st.width, st.height, k)
                        fr.alpha_composite(cr, (int(cx - cr.width / 2), int(cy - cr.height / 2)))
                    if o["text"]:
                        tg = tag_image(o["text"], 60)
                        place(fr, tg, cx, cy + st.height / 2 + tg.height / 2 - 10, p, o["motion"])
            last = fr.convert("RGB").tobytes()
            last_key = key
        ff.stdin.write(last)
    Image.frombytes("RGB", (W, H), last).save(f"frames/{len(scenes):03d}.png")
    ff.stdin.close()
    ff.wait()
    pacing([s["t0"] for s in scenes] + [o["t"] for s in scenes for o in s["ov"]], total, out)
    L = [s["t1"] - s["t0"] for s in scenes]
    print(f"{os.path.abspath(out)}: {len(scenes)} scenes, {sum(len(s['ov']) for s in scenes)} overlays, "
          f"{total:.1f}s, mean shot {sum(L) / len(L):.2f}s")


# ------------------------------------------------------------------ main
def selfcheck():
    for name in LOOKS:
        set_look(name)
        fr = card()
        label(fr, "THE OLDEST FIRE?|सबसे पुरानी आग? श्री क्षत्रिय", "big")
        fr.resize((640, 360)).save(f"selfcheck_{name}.png")
    print("wrote selfcheck_<look>.png for", ", ".join(LOOKS), "- open one: the Hindi must have joined conjuncts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio")
    ap.add_argument("--out")
    ap.add_argument("--look", choices=LOOKS)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--pacing", action="store_true", help="only report long holds, render nothing")
    a = ap.parse_args()
    if a.selfcheck:
        return selfcheck()
    look = a.look
    if not look and os.path.exists("STYLE.txt"):
        first = open("STYLE.txt", encoding="utf-8").readline()
        if first.lower().startswith("look:"):
            look = first.split(":", 1)[1].strip()
    set_look(look if look in LOOKS else "bright")
    audio = a.audio or ("mix.wav" if os.path.exists("mix.wav") else "VO.wav")
    words = {f"{r['line']}.{r['i']}": max(0.0, float(r["start"]))
             for r in csv.DictReader(open("WORDS.tsv", encoding="utf-8"), delimiter="\t")}
    rows = [r for r in csv.reader(open("SCENES.tsv", encoding="utf-8"), delimiter="\t")
            if r and r[0].strip() and not r[0].startswith("#") and r[0] != "cue"]
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "csv=p=0", audio], capture_output=True, text=True).stdout)
    if "--pacing" in sys.argv:                     # report only, render nothing
        ev = []
        for r in rows:
            c = r[0].strip().lstrip("+")
            if c in words:
                ev.append(words[c] if r[0].strip().startswith("+") or ev else 0.0)
        return pacing(ev, total, None)
    missing = sorted({r[1] for r in rows if r[1] not in ("card", "count", "tag") and not os.path.exists(r[1])})
    if missing:
        sys.exit("missing pictures: " + ", ".join(missing))
    out = a.out or os.path.basename(os.getcwd()) + ".mp4"
    if any(r[0].strip().startswith("+") for r in rows):
        return render_motion(rows, words, total, audio, out)
    starts = []
    for r in rows:
        c = r[0].strip()
        if c not in words:
            sys.exit(f"cue {c} is not a line.word in WORDS.tsv")
        starts.append(words[c])
    starts[0] = 0.0
    bad = [i for i in range(1, len(starts)) if starts[i] <= starts[i - 1]]
    if bad:
        sys.exit(f"SCENES.tsv row {bad[0] + 1} (cue {rows[bad[0]][0]}) does not come after the row before it")
    os.makedirs("frames", exist_ok=True)
    cache, lst = {}, []
    for i, r in enumerate(rows):
        r += [""] * (5 - len(r))
        _, img, text, pos, extra = [x.strip() for x in r[:5]]
        if img == "card":
            fr = card()
        else:
            if img not in cache:
                cache[img] = picture(img)
            fr = cache[img].copy()
        blocked = []
        if extra.startswith("bars:"):
            bars(fr, extra[5:])
            blocked.append(CHART)
        if text:
            label(fr, text, "big" if img == "card" else (pos if pos.endswith("!") else "auto"), blocked)
        p = os.path.abspath(f"frames/{i + 1:03d}.png")
        fr.save(p)
        end = starts[i + 1] if i + 1 < len(rows) else total
        lst.append(f"file '{p}'\nduration {end - starts[i]:.3f}")
    lst.append(f"file '{p}'")                              # the concat demuxer needs the last file twice
    open("frames/list.txt", "w", encoding="utf-8").write("\n".join(lst).replace("\\", "/"))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "frames/list.txt",
                    "-i", audio, "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-threads", "3", "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
    L = [b - s for s, b in zip(starts, starts[1:] + [total])]
    print(f"{os.path.abspath(out)}: {len(rows)} scenes, {total:.1f}s, mean shot {sum(L) / len(L):.2f}s, "
          f"longest {max(L):.1f}s (on '{rows[L.index(max(L))][0]}')")


if __name__ == "__main__":
    main()
