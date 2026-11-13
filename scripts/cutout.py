# -*- coding: utf-8 -*-
"""Flow returns each element as one object on flat white. Turn that into a
clean transparent PNG: luminance threshold + flood fill from the border, so
white *inside* the object stays opaque.

usage:  python cutout.py <src_dir> <dst_dir>
        python cutout.py --demo        # self-check, no Flow needed
"""
import os, sys, glob
import numpy as np
from PIL import Image
from scipy import ndimage

WHITE_LO, WHITE_HI = 228, 248      # alpha ramps from 1 to 0 across this band
MIN_PIECE = 0.02                   # drop components under 2% of the biggest:
                                   # the watermark and stray specks, never a real
                                   # second piece (three grains, a boulder cluster)


def drop_specks(alpha):
    """Remove everything much smaller than the main subject: the Gemini sparkle
    in the corner, and any rim crumbs the threshold left behind. Both extraction
    paths need this, so it lives in one place."""
    # Threshold low, not at 0.5: the Gemini sparkle is translucent, so it lands
    # around alpha 0.3 and a 0.5 cut walks straight past it, leaving a faint
    # ghost in the corner. A real object's soft edge is connected to its body,
    # so a low threshold costs nothing.
    solid = alpha > 0.1
    lbl, n = ndimage.label(solid)
    if n <= 1:
        return alpha
    sizes = ndimage.sum(solid, lbl, range(1, n + 1))
    keep = 1 + np.flatnonzero(sizes >= sizes.max() * MIN_PIECE)
    return np.where(np.isin(lbl, keep), alpha, 0.0)


def cutout(src, pad=12):
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    lum = a.max(axis=2)                       # max channel: a pale tint is not white
    sat = a.max(axis=2) - a.min(axis=2)
    paperish = (lum >= WHITE_LO) & (sat <= 22)

    # background = the near-white region connected to the border, so enclosed
    # white (a window pane, the gap in a hourglass frame) survives
    lbl, n = ndimage.label(paperish)
    border = set(lbl[0].tolist()) | set(lbl[-1].tolist()) | \
             set(lbl[:, 0].tolist()) | set(lbl[:, -1].tolist())
    border.discard(0)
    bg = np.isin(lbl, list(border)) if border else np.zeros_like(paperish)

    # An enclosed region that is the SAME colour as the border background, and
    # flat, is a hole the background shows through -- the gap inside a shovel's
    # D-grip. Reachability alone cannot see it, and it is what left white
    # sitting in that grip. A real white object part is never this exact:
    # the cream mug reads 244 and the cement sack 246, both far outside the
    # tolerance, and both carry shading (a much higher spread).
    if border:
        ref = a[bg].mean(axis=0)
        for i in range(1, n + 1):
            if i in border:
                continue
            m = lbl == i
            if m.sum() < 300:
                continue
            px = a[m]
            if np.abs(px.mean(axis=0) - ref).max() < 4 and px.std() < 6:
                bg = bg | m

    # Anything not reached from the border is subject -- INCLUDING white.
    # That is the whole point of this path: a phone screen, a cream mug and a
    # cement sack are all white-ish and all enclosed, so luminance alone must
    # never decide. Only reachability, or an exact background-colour match, does.
    alpha = (~bg).astype(float)

    # ...except magenta. These images were all prompted on magenta, so when one
    # comes back mostly white the model has usually still left magenta in the
    # enclosed holes (the shovel's D-grip). Reachability cannot get in there,
    # but the key colour is unambiguous wherever it appears.
    from key import magentaness, KEY_HI
    mg = magentaness(a.astype(float))
    alpha = np.where(mg > KEY_HI, 0.0, alpha)

    alpha = drop_specks(alpha)

    # The rim pixels here are raw JPEG blends toward the white background, so
    # they read as a pale halo, and weak magenta spill reads violet. Same cure
    # as the magenta path: hand every unconfident pixel the colour of the
    # nearest confident one, so a rim can never be lighter than its object.
    # Erode to pick the confident pixels: alpha here is still hard 0/1 (the
    # feather is applied further down), so without eroding, the boundary band
    # counts as confident and keeps its pale JPEG blend -- which is exactly the
    # halo this is meant to remove.
    rgb = np.asarray(im).astype(float)
    conf = ndimage.binary_erosion(alpha > 0.5, iterations=2) & (mg <= 10)
    if conf.any():
        idx = ndimage.distance_transform_edt(~conf, return_indices=True)[1]
        rgb = np.where(conf[..., None], rgb, rgb[idx[0], idx[1]])

    out = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])
    img = Image.fromarray(out, "RGBA")
    from PIL import ImageFilter
    img.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))
    bb = img.getbbox()
    if bb:
        x0, y0, x1, y1 = bb
        img = img.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(img.width, x1 + pad), min(img.height, y1 + pad)))
    return img


def demo():
    """A white frame, a black disc, and a white hole inside the disc, plus a
    grey speck in the corner standing in for the watermark."""
    from PIL import ImageDraw
    im = Image.new("RGB", (400, 400), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((100, 100, 300, 300), fill=(40, 60, 120))
    d.ellipse((170, 170, 230, 230), fill=(244, 240, 228))   # enclosed CREAM: keep
    d.rectangle((120, 250, 150, 280), fill=(255, 255, 255))  # enclosed EXACT bg: drop
    d.rectangle((370, 370, 392, 392), fill=(200, 200, 200))  # "watermark"
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_demo.png")
    im.save(p)
    c = cutout(p, pad=0)
    a = np.asarray(c)[:, :, 3]
    # cropped to the disc (201px inclusive), so the speck was dropped
    assert max(c.size) <= 205, ("cropped to the disc, not the speck", c.size)
    assert a[100, 100] > 200, "enclosed cream must stay opaque"
    assert a[165, 35] < 40, "enclosed region identical to the background is a hole"
    assert a[20, 100] > 200, "the disc body must be opaque"
    # the disc is inscribed in the crop, so a corner of the crop is outside it
    assert a[3, 3] < 30, ("outside the disc must be transparent", a[3, 3])
    os.remove(p)
    print("cutout demo OK - disc kept, enclosed white kept, watermark speck dropped")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo(); raise SystemExit
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src, "*.png")) +
                    glob.glob(os.path.join(src, "*.jpg"))):
        o = os.path.join(dst, os.path.splitext(os.path.basename(f))[0] + ".png")
        if os.path.exists(o):
            continue
        cutout(f).save(o)
        print("cut", os.path.basename(o), flush=True)
