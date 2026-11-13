"""Erase Flow's Gemini sparkle from every scene picture with LaMa (big-lama), the clean way.

Run from the project folder:
    python <skill>/scripts/delama.py --watch      # in the BACKGROUND while Flow generates: cleans every
                                                  # download the moment it lands (cache keyed by content)
    python <skill>/scripts/delama.py              # after `pictures.py pick`: img/sNN.jpg -> img/clean/sNN.png
                                                  # (instant for anything --watch already cleaned)
    python <skill>/scripts/delama.py --force      # redo all
    python <skill>/scripts/delama.py --selfcheck  # erase a drawn mark on a test picture, print the error

render.py uses img/clean/<name>.png automatically when it exists; without it, it falls back to
a smooth fill (fine on sky and walls, slightly soft on busy corners).

Why only a corner crop: the mark sits at a fixed spot (~58 px box, inset ~70 px from the
bottom-right of a 1376x768 Flow picture), so LaMa runs on a 384x384 corner, about 1-2 s per
picture on CPU, and every pixel outside the mark stays identical.

Needs: torch (CPU is fine) and the model file ~/.cache/lama/big-lama.pt (206 MB, Apache-2.0,
LaMa by Samsung AI / advimman; TorchScript build from the simple-lama-inpainting release).
SETUP.md step 3b installs both. Override the model path with LAMA_MODEL.
"""
import glob, hashlib, os, shutil, sys, time, warnings
import numpy as np
from PIL import Image, ImageFilter

MODEL = os.environ.get("LAMA_MODEL", os.path.join(os.path.expanduser("~"), ".cache", "lama", "big-lama.pt"))
CROP = 384
CACHE = os.path.join("img", "lama_cache")          # <md5 of the Flow file>.png, shared by --watch and pick


def mark_box(w, h):
    """Same geometry as render.unmark: the sparkle box, padded."""
    x0, y0 = w - 126, h - 126
    return x0 - 8, y0 - 8, x0 + 70, y0 + 70


_model = None


def model():
    global _model
    if _model is None:
        import torch
        if not os.path.exists(MODEL):
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _model = torch.jit.load(MODEL, map_location="cpu").eval()
    return _model


def erase(im, box):
    """LaMa on a CROPxCROP window around box; only the box (feathered) is replaced.
    Falls back to harmonic unmark if big-lama model is not locally cached."""
    m_obj = model()
    if m_obj is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from render import unmark
            return unmark(im)
        except Exception:
            arr = np.array(im.convert("RGB"))
            w, h = im.size
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[box[1]:box[3], box[0]:box[2]] = 255
            import cv2
            clean = cv2.inpaint(arr, mask, 5, cv2.INPAINT_TELEA)
            return Image.fromarray(clean)

    import torch
    im = im.convert("RGB")
    w, h = im.size
    cx0, cy0 = max(0, min(w - CROP, box[2] - CROP + 40)), max(0, min(h - CROP, box[3] - CROP + 40))
    win = im.crop((cx0, cy0, cx0 + CROP, cy0 + CROP))
    m = Image.new("L", win.size, 0)
    m.paste(255, (box[0] - cx0, box[1] - cy0, box[2] - cx0, box[3] - cy0))
    img_t = torch.from_numpy(np.asarray(win, np.float32) / 255).permute(2, 0, 1)[None]
    msk_t = (torch.from_numpy(np.asarray(m, np.float32) / 255) > 0.5).float()[None, None]
    with torch.no_grad():
        out = m_obj(img_t, msk_t)[0].permute(1, 2, 0).numpy()
    res = Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8))
    soft = m.filter(ImageFilter.GaussianBlur(3)).point(lambda v: min(255, v * 2))
    win.paste(res, (0, 0), soft)
    im.paste(win, (cx0, cy0))
    return im


def selfcheck():
    rng = np.random.default_rng(1)
    base = np.zeros((768, 1376, 3), np.uint8)
    base[:] = (120, 180, 230)
    base[500:, :] = (90, 170, 80)
    base = Image.fromarray((base + rng.normal(0, 4, base.shape)).clip(0, 255).astype(np.uint8))
    marked = base.copy()
    box = mark_box(*base.size)
    from PIL import ImageDraw
    ImageDraw.Draw(marked).ellipse((box[0] + 14, box[1] + 14, box[2] - 14, box[3] - 14), fill=(250, 250, 250))
    clean = erase(marked, box)
    a = np.asarray(clean, np.float32)[box[1]:box[3], box[0]:box[2]]
    b = np.asarray(base, np.float32)[box[1]:box[3], box[0]:box[2]]
    err = float(np.abs(a - b).mean())
    clean.crop((box[0] - 60, box[1] - 60, box[2] + 40, box[3] + 40)).save("delama_selfcheck.png")
    print(f"mean error in the erased box: {err:.1f} (under 12 is clean) -> delama_selfcheck.png")
    sys.exit(0 if err < 12 else 1)


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def clean_into_cache(src):
    """LaMa-clean one Flow file into the cache (by content); return the cache path."""
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, md5(src) + ".png")
    if not os.path.exists(out):
        im = Image.open(src)
        if im.width < 400 or im.height < 300:
            return None
        erase(im, mark_box(*im.size)).save(out)
    return out


def watch():
    """Poll the project's Flow download folder and clean each new picture as it arrives.
    Stops by itself after 20 quiet minutes, or with Ctrl+C / a task stop."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pictures import folder
    root = os.environ.get("FLOW_DOWNLOADS") or os.path.join(os.path.expanduser("~"), "Downloads")
    done, quiet = set(), time.time()
    print(f"watching for {folder()} under {root}", flush=True)
    while time.time() - quiet < 20 * 60:
        hits = [p for depth in range(4)
                for d in glob.glob(os.path.join(root, *(["*"] * depth), folder()))
                for p in glob.glob(os.path.join(d, "*.jpg")) + glob.glob(os.path.join(d, "*.png"))]
        new = [p for p in sorted(hits) if p not in done and time.time() - os.path.getmtime(p) > 3]
        for p in new:
            if clean_into_cache(p):
                print(f"cleaned {os.path.basename(p)}", flush=True)
            done.add(p)
            quiet = time.time()
        time.sleep(15)
    print("no new pictures for 20 minutes; watcher stopped")


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    if "--watch" in sys.argv:
        return watch()
    os.makedirs("img/clean", exist_ok=True)
    todo = sorted(glob.glob("img/s*.jpg") + glob.glob("img/s*.png"))
    n = cached = 0
    for p in todo:
        out = os.path.join("img", "clean", os.path.splitext(os.path.basename(p))[0] + ".png")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(p) and "--force" not in sys.argv:
            continue
        c = os.path.join(CACHE, md5(p) + ".png")
        if os.path.exists(c) and "--force" not in sys.argv:
            shutil.copy(c, out)
            cached += 1
            continue
        res = clean_into_cache(p)
        if res:
            shutil.copy(res, out)
            n += 1
            print(f"cleaned {p}", flush=True)
    print(f"img/clean/ ready: {cached} from the --watch cache, {n} cleaned now ({len(todo)} pictures)")


if __name__ == "__main__":
    main()
