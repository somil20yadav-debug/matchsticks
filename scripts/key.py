# -*- coding: utf-8 -*-
"""Chroma-key the fixed magenta background off a Flow element and write a
transparent PNG.

Why magenta and not white: white keying can only remove background that is
connected to the image border, so an enclosed white region is ambiguous -- the
phone's screen must stay, the hourglass frame's gaps must go, and nothing in
the pixels says which is which. A background colour the object never contains
removes that ambiguity: every magenta pixel is background, inside or outside.

usage:  python key.py <src_dir> <dst_dir>
        python key.py --demo
"""
import os, sys, glob
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

# "Magenta-ness": how far red AND blue both sit above green. Pure magenta
# scores 255. Every colour in the VOX palette scores at or below zero --
# cream -12, coral -15, muted blue -36, terracotta -34, black/grey/white 0 --
# so this separates background from subject far more cleanly than Euclidean
# distance to the key colour, which was still passing dark magenta JPEG fringe
# through and despilling it into a navy outline.
KEY_HI = 40.0    # at or above this, it is background
KEY_LO = -15.0   # at or below this, it is subject

# Saturation gate, calibrated PER IMAGE. A 1-2px dark bar against magenta (the
# truck's handrail, the crane's lattice) has its chroma contaminated by JPEG's
# half-resolution colour and reads as magenta-ish but dull, so saturation is
# what separates it from true background. The thresholds cannot be constants:
# the model does not always render the same magenta -- most images come back at
# saturation ~253, but the dunes came back at 155, and fixed thresholds then
# read that whole background as "dull magenta" and restored it as a grey slab.
SAT_HI_FRAC = 0.85   # at this fraction of the measured background saturation, background
SAT_LO_FRAC = 0.45   # below this fraction, subject


def magentaness(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return np.minimum(r, b) - g


def key(src, pad=10, crop=True):
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(float)

    mg = magentaness(a)
    sat = a.max(axis=2) - a.min(axis=2)

    # ---- unmixing key -------------------------------------------------------
    # The edge is soft because the source is a 4:2:0 JPEG: colour is stored at
    # half resolution, so magenta physically smears ~2px into every border. The
    # honest model of such a pixel is a composite, C = alpha*F + (1-alpha)*B,
    # so solve it rather than threshold it. Measuring the background's own
    # magenta-ness makes this self-calibrating -- it needs no tuned constants
    # and it copes with the washed-out magenta some images come back on.
    ring = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    B = np.median(ring[magentaness(ring.astype(float)) > KEY_HI], axis=0) \
        if (magentaness(ring.astype(float)) > KEY_HI).any() else np.array([255., 0., 255.])
    mg_b = max(magentaness(B.reshape(1, 1, 3))[0, 0], 1.0)
    alpha = np.clip(1.0 - mg / mg_b, 0.0, 1.0)

    from cutout import drop_specks
    alpha = drop_specks(alpha)

    # Recover the true foreground colour by removing the background's measured
    # contribution: F = (C - (1-alpha)*B) / alpha. This is what kills the violet
    # for good. Clamping red and blue down to green (what ran here before) only
    # HIDES spill by darkening it, which is why a trace always survived; solving
    # for F removes it, because the magenta is subtracted out rather than capped.
    # Guarded at low alpha, where dividing by alpha would amplify JPEG noise.
    safe = np.maximum(alpha, 0.25)[..., None]
    F = (a - (1.0 - alpha)[..., None] * B.reshape(1, 1, 3)) / safe

    # Colour extension. Where alpha is low there is not enough signal to solve
    # honestly -- dividing by a small alpha amplifies JPEG noise, and the old
    # fallback (use the pixel's luminance) turned that amplified noise into a
    # pale rim, which is the whitish edge visible when you zoom in. Instead give
    # every unconfident pixel the colour of the nearest CONFIDENT one, so the rim
    # is always the object's own colour and can never be brighter than it.
    # JPEG ringing: at a very sharp corner the DCT overshoots and leaves a pale
    # speck baked into the source (measured at 22x the image's average edge
    # gradient). It is only a handful of pixels, but it is free to drop -- treat
    # an ISOLATED pale blob as unconfident too, so it gets the nearest real
    # colour. Size-gated, so genuinely pale objects (the cream mug, the white
    # glass) are untouched: those are large regions, not specks.
    Yf = (F * np.array([0.299, 0.587, 0.114])).sum(axis=2)
    pale = (Yf > 150) & ((F.max(axis=2) - F.min(axis=2)) < 60)
    lbl, k = ndimage.label(pale)
    ring = np.zeros_like(pale)
    if k:
        sizes = ndimage.sum(pale, lbl, range(1, k + 1))
        ring = np.isin(lbl, 1 + np.flatnonzero(sizes <= 20))

    conf = (alpha > 0.70) & ~ring
    if conf.any():
        idx = ndimage.distance_transform_edt(~conf, return_indices=True)[1]
        F = np.where(conf[..., None], F, F[idx[0], idx[1]])
    out = np.clip(F, 0, 255)

    # Tighten the ramp. Unmixing gives a physically correct but wide transition;
    # a smoothstep pulls it toward a crisp edge while staying anti-aliased, so
    # the border reads clean instead of smeared.
    al = np.clip((alpha - 0.30) / 0.40, 0, 1)
    al = al * al * (3 - 2 * al)

    img = Image.fromarray(np.dstack([out.astype(np.uint8),
                                     (al * 255).astype(np.uint8)]), "RGBA")

    bb = img.getbbox() if crop else None
    if bb:
        x0, y0, x1, y1 = bb
        img = img.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(img.width, x1 + pad), min(img.height, y1 + pad)))
    return img


def coverage(p):
    """Fraction of the frame that survived the key -- a quick sanity number."""
    a = np.asarray(Image.open(p).convert("RGBA"))[..., 3]
    return (a > 128).mean()


def bleed(src):
    """How much of the frame is caught in the magenta bleed band -- neither
    clean background nor clean subject. This is the one number that predicts
    whether a cut-out will look crisp, and it varies per GENERATION, not per
    prompt: two hourglasses from the identical prompt scored 2.3% and 4.3%.
    So it is a QC gate, not a tuning knob -- score every element, regenerate
    the ones over the threshold rather than accepting whatever arrived."""
    a = np.asarray(Image.open(src).convert("RGB")).astype(float)
    ring = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    sel = magentaness(ring.astype(float)) > KEY_HI
    if not sel.any():
        return float("inf")                      # came back on white: redo
    mgb = magentaness(np.median(ring[sel], axis=0).reshape(1, 1, 3))[0, 0]
    mg = magentaness(a)
    return float(((mg > 20) & (mg < mgb * 0.85)).mean() * 100)


REDO_OVER = 2.5    # b2 1.57, b3 1.48 -- the ones judged perfect sit well under this


def bg_is_magenta(src):
    """Judge from the border ring, not the whole frame: an object that fills
    95% of the image (the window frame) leaves only a sliver of background,
    and a coverage test reads that as 'not magenta' and picks the wrong path."""
    a = np.asarray(Image.open(src).convert("RGB")).astype(float)
    mg = magentaness(a)
    ring = np.concatenate([mg[0], mg[-1], mg[:, 0], mg[:, -1]])
    return np.median(ring) > KEY_HI


def extract(src, pad=10):
    """Nano Banana honours the magenta background about nine times in ten; the
    rest come back on plain white. Pick the method that matches what actually
    arrived rather than failing on the minority: magenta keys everywhere at
    once, white can only be flood-filled inward from the border (so interior
    holes stay filled -- fine for the simple shapes that tend to come back
    this way, and the reason magenta is still the default)."""
    if bg_is_magenta(src):
        return key(src, pad=pad), "magenta"
    from cutout import cutout
    return cutout(src, pad=pad), "white"


def demo():
    """An object with BOTH cases: an enclosed cream panel that must survive,
    and an enclosed magenta gap that must key out."""
    from PIL import ImageDraw
    im = Image.new("RGB", (400, 400), (255, 0, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((80, 60, 320, 340), fill=(40, 48, 62))        # dark body
    d.rectangle((110, 95, 290, 250), fill=(244, 240, 228))    # cream screen: KEEP
    d.rectangle((150, 275, 250, 315), fill=(255, 0, 255))     # cut-out gap: DROP
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_keydemo.png")
    im.save(p)
    a = np.asarray(key(p, crop=False))[..., 3]   # full frame, no bbox shift
    assert a[170, 200] > 200, "enclosed cream panel must stay opaque"
    assert a[200, 20] < 40, "outside the object must be transparent"
    gap = a[295, 200]
    assert gap < 40, ("enclosed magenta gap must key out, got alpha %d" % gap)
    body = a[80, 200]
    assert body > 200, ("dark body must stay opaque, got %d" % body)
    os.remove(p)
    print("key demo OK - cream panel kept, magenta gap removed, outside removed")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo(); raise SystemExit
    if "--qc" in sys.argv:
        src = sys.argv[sys.argv.index("--qc") + 1]
        bad = []
        for f in sorted(glob.glob(os.path.join(src, "*.jpg"))):
            s = bleed(f)
            if s > REDO_OVER:
                bad.append((s, os.path.basename(f)))
        for s, n in sorted(bad, reverse=True):
            print("REDO %6s  %s" % ("white" if s == float("inf") else "%.2f%%" % s, n))
        print("%d of %d need regenerating" % (len(bad), len(glob.glob(os.path.join(src, "*.jpg")))))
        raise SystemExit
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src, "*.jpg")) + glob.glob(os.path.join(src, "*.png"))):
        o = os.path.join(dst, os.path.splitext(os.path.basename(f))[0] + ".png")
        img, how = extract(f)
        img.save(o)
        print("%-8s %-44s %.1f%% kept" % (how, os.path.basename(o)[:44], coverage(o) * 100), flush=True)
