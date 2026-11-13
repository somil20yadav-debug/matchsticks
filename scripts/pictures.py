"""Pictures for a stickman explainer, through Google Flow (flow-auto). Run from the project folder.

    python <skill>/scripts/pictures.py refs <sheet.jpg> --names modern,caveman [--cuts 0.5]
        a character sheet -> img/sheet.jpg + one reference per character (img/ref_<name>.jpg)
    python <skill>/scripts/pictures.py submit 1 8          # test 2 shots first (look + characters)
    python <skill>/scripts/pictures.py submit              # every shot in SHOTS.tsv, no --wait
    python <skill>/scripts/pictures.py submit 5-9 14 --new-project
    python <skill>/scripts/pictures.py submit --dry       # print the commands, generate nothing
    python <skill>/scripts/pictures.py review [from to]    # labelled grid of the downloads -> review.jpg
    python <skill>/scripts/pictures.py pick                # downloads -> img/sNN.jpg (PICK.tsv fixes swaps)
    python <skill>/scripts/pictures.py qc                  # frames/ -> qc.jpg contact sheet after render
    python <skill>/scripts/pictures.py elements [ids]      # ELEMENTS.tsv -> cut-out objects on magenta (1:1)
    python <skill>/scripts/pictures.py cutouts             # downloads -> elements/cut/NN.png (magenta keyed off)

ELEMENTS.tsv  id, ref, object   one object or one character pose per row, for the hybrid look (PLAYBOOK §9).
              Downloads land in stick_<project>_el; ELPICK.tsv (shot, file) fixes swaps like PICK.tsv.

SHOTS.tsv  id, ref, prompt[, space]   ref = - (no character) | a name from refs (img/ref_<name>.jpg) | sheet
           space = right | left | top | - : that 40% of the picture stays empty and render.py puts stickers
           there; MIX the sides across a film so frames do not all look alike
           flip = yes: render.py mirrors the picture (after LaMa), e.g. a right-empty picture used as left
STYLE.txt  line 1 "look: <name>", then the style paragraph appended to every prompt (from looks/<name>.md,
           adapted to the topic)
PICK.tsv   shot, file   only for shots whose picture came back under another number (Flow mispairs in
           batches; decide by LOOKING at review.jpg). file = the download's number.

Downloads are found under ~/Downloads (any depth up to 3) in the folder stick_<project>, or set
FLOW_DOWNLOADS to that folder. Batch size: STICK_BATCH (default 4). Model: STICK_MODEL (default
nano-banana-2, which Flow labels "Nano Banana 2.1"; do not use nano-banana-pro for this style).
"""
import csv, glob, hashlib, os, re, shutil, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import unmark  # noqa: E402

FIX = (" The attached image is only a character design reference: keep the same face, hair, proportions and "
       "line style (change clothes only if this prompt says so) and draw each person only once, inside the "
       "scene. Ignore the reference's backdrop and colour tone, and do not copy its line-up.")
# Nano Banana 2 (Flow shows it as "Nano Banana 2.1"): clean, clear pictures. Never Pro for this style.
MODEL = os.environ.get("STICK_MODEL", "nano-banana-2")
NO_TEXT = " Absolutely no text, no letters, no numbers, no labels, no watermark."


def folder():
    d = os.environ.get("STICK_FOLDER")
    if d:
        return d
    base = re.sub(r"[^a-z0-9_-]", "", os.path.basename(os.getcwd()).lower())
    root = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.exists(os.path.join(root, base)):
        return base
    return "stick_" + base


def downloads():
    d = os.environ.get("FLOW_DOWNLOADS")
    if d:
        return d
    root = os.path.join(os.path.expanduser("~"), "Downloads")
    for depth in range(4):
        hit = glob.glob(os.path.join(root, *(["*"] * depth), folder()))
        if hit:
            return hit[0]
    sys.exit(f"no folder named {folder()} under {root} yet. If Flow saves elsewhere, set FLOW_DOWNLOADS.")


def ids(args):
    out = []
    for a in args:
        if "-" in a:
            x, y = a.split("-")
            out += range(int(x), int(y) + 1)
        else:
            out.append(int(a))
    return set(out)


def shots():
    return list(csv.DictReader(open("SHOTS.tsv", encoding="utf-8"), delimiter="\t"))


def style():
    lines = open("STYLE.txt", encoding="utf-8").read().splitlines()
    body = " ".join(l for l in lines if l.strip() and not l.lower().startswith("look:"))
    return " Style: " + body.strip() + NO_TEXT


def refs(a):
    sheet = a[0]
    names = a[a.index("--names") + 1].split(",")
    cuts = [float(c) for c in a[a.index("--cuts") + 1].split(",")] if "--cuts" in a else \
        [i / len(names) for i in range(1, len(names))]
    os.makedirs("img", exist_ok=True)
    im = unmark(Image.open(sheet))
    im.save("img/sheet.jpg", quality=95)
    xs = [0] + [int(c * im.width) for c in cuts] + [im.width]
    for n, x0, x1 in zip(names, xs, xs[1:]):
        im.crop((x0, 0, x1, im.height)).save(f"img/ref_{n}.jpg", quality=95)
    print("wrote img/sheet.jpg and", ", ".join(f"img/ref_{n}.jpg" for n in names), "- look at each one")


def layout_check():
    """Warn when the space column repeats: 3 of the same side in a row, or one side on over 40% of shots.
    Layouts are chosen per shot from its line, so every film gets its own mix (PLAYBOOK section 9)."""
    sides = [((r.get("space") or "").strip().lower() or "-") for r in shots()]
    warn = []
    for i in range(2, len(sides)):
        if sides[i] == sides[i - 1] == sides[i - 2]:
            warn.append(f"shots {i - 1}-{i + 1} are all '{sides[i]}'")
    for side in set(sides):
        if len(sides) >= 8 and sides.count(side) / len(sides) > 0.4:
            warn.append(f"'{side}' is used on {sides.count(side)} of {len(sides)} shots")
    print("layout:", " ".join(sides))
    for w in warn:
        print("LAYOUT WARNING:", w, "- vary it by what each line needs")


def submit(a):
    exe = shutil.which("flow-auto") or sys.exit("flow-auto is not installed (Flow Connector prerequisite)")
    want = ids([x for x in a if not x.startswith("--")])
    new = "--new-project" in a
    layout_check()
    st = style()
    batch = os.environ.get("STICK_BATCH", "4")
    n = 0
    for r in shots():
        i = int(r["id"])
        if want and i not in want:
            continue
        ref, prompt = r["ref"].strip(), r["prompt"].strip()
        side = (r.get("space") or "").strip().lower()
        if side in ("left", "right"):             # leave room for stickers so they never cover the subject
            keep = "left" if side == "right" else "right"
            prompt += (f" Composition: a complete, natural, full scene that fills the whole frame, with the main "
                       f"character and the main subject placed slightly towards the {keep}, and a calmer, less busy "
                       f"area on the {side} side (open sky, plain wall, ground or water) without important details. "
                       f"The scene must still look finished and rich, not empty.")
        elif side == "top":
            prompt += (" Composition: a complete, natural, full scene that fills the whole frame, with the main "
                       "character and the main subject in the lower part and a calm open sky or plain upper wall above "
                       "them without important details. The scene must still look finished and rich, not empty.")
        cmd = [exe, "generate", "create", "flow-text-to-image" if ref == "-" else "flow-image-to-image",
               "--model", MODEL, "--aspect-ratio", "16:9", "--outputs", "1", "--batch", batch,
               "--index", str(i), "--folder", folder()]
        if new and n == 0:
            cmd.append("--new-project")              # one project per RUN: only on the first prompt
        if ref != "-":
            p = "img/sheet.jpg" if ref == "sheet" else f"img/ref_{ref}.jpg"
            if not os.path.exists(p):
                sys.exit(f"shot {i}: reference {p} is missing (run: pictures.py refs ...)")
            cmd += ["--image", p]
            prompt += FIX
        if "--dry" in a:
            print(" ".join(cmd[1:]), "--prompt", repr((prompt + st)[:90] + "..."))
            n += 1
            continue
        res = subprocess.run(cmd + ["--prompt", prompt + st], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        print(f"shot {i:02d}: {(res.stdout or res.stderr).strip().splitlines()[0] if (res.stdout or res.stderr) else '?'}")
        n += 1
    print(f"{n} shots submitted to folder {folder()}. Watch: flow-auto generate list   Holes: flow-auto generate list --failed")


def files():
    d = downloads()
    out = {}
    raw = glob.glob(os.path.join(d, "*.jpg")) + glob.glob(os.path.join(d, "*.png")) + glob.glob(os.path.join(d, "*.webp"))
    for p in sorted(raw):
        base_low = os.path.basename(p).lower()
        if "sheet" in base_low or "character" in base_low or "cast" in base_low or "prop" in base_low:
            continue
        m = re.match(r"(\d+) - ", os.path.basename(p))
        if m:
            out.setdefault(int(m.group(1)), []).append(p)   # first = the original, " (1)" etc. are re-submits
    return out


def grid(paths, tags, out, tw=400, th=225, cols=5):
    g = Image.new("RGB", (tw * cols, th * ((len(paths) + cols - 1) // cols)), "white")
    d = ImageDraw.Draw(g)
    try:
        f = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        f = ImageFont.load_default()
    for k, (p, t) in enumerate(zip(paths, tags)):
        x, y = k % cols * tw, k // cols * th
        g.paste(Image.open(p).convert("RGB").resize((tw, th)), (x, y))
        if t:
            d.rectangle((x, y, x + 64, y + 32), fill="black")
            d.text((x + 6, y + 3), t, fill="yellow", font=f)
    g.save(out, quality=85)
    print(f"{os.path.abspath(out)}: {len(paths)} pictures")


def review(a):
    lo, hi = (int(a[0]), int(a[1])) if len(a) > 1 else (1, 9999)
    fs = files()
    keys = [k for k in sorted(fs) if lo <= k <= hi]
    grid([fs[k][0] for k in keys], [str(k) for k in keys], "review.jpg")
    have = {int(r["id"]) for r in shots()}
    gone = sorted(have - set(fs))
    if gone:
        print("not downloaded yet:", " ".join(map(str, gone)))


def pick(a):
    fs = files()
    swap = {}
    if os.path.exists("PICK.tsv"):
        for r in csv.DictReader(open("PICK.tsv", encoding="utf-8"), delimiter="\t"):
            swap[int(r["shot"])] = int(r["file"])
    os.makedirs("img", exist_ok=True)
    seen, missing = {}, []
    for r in shots():
        s = int(r["id"])
        f = swap.get(s, s)
        if f not in fs:
            missing.append(s)
            continue
        src = fs[f][0]
        h = hashlib.md5(open(src, "rb").read()).hexdigest()
        if h in seen:
            print(f"WARNING shot {s} is byte-identical to shot {seen[h]} (Flow re-used an old tile): regenerate it")
        seen[h] = s
        if src.lower().endswith(".webp"):
            Image.open(src).convert("RGB").save(f"img/s{s:02d}.jpg", quality=95)
        else:
            shutil.copy(src, f"img/s{s:02d}.jpg")
    print(f"copied {len(seen)} pictures to img/" + (f"; missing: {' '.join(map(str, missing))}" if missing else ""))


def qc(a):
    ps = sorted(glob.glob("frames/[0-9]*.png"))
    grid(ps, [""] * len(ps), "qc.jpg", 384, 216, 6)


EL_PROMPT = (" Hand-drawn 2D cartoon sticker for a stickman explainer: clean dark ink outline, flat bright colours "
             "with soft shading, ONE single isolated subject, centred with a generous empty margin on all sides, on a "
             "solid flat pure magenta background, uniform chroma-key magenta #FF00FF filling the entire background and "
             "showing through every gap, the subject itself contains no magenta or pink anywhere, hard crisp edges, no "
             "drop shadow, no glow, no ground, no scenery, no text, no letters, no numbers, no watermark.")


def elements(a):
    exe = shutil.which("flow-auto") or sys.exit("flow-auto is not installed (Flow Connector prerequisite)")
    want = ids([x for x in a if not x.startswith("--")])
    rows = list(csv.DictReader(open("ELEMENTS.tsv", encoding="utf-8"), delimiter="	"))
    n = 0
    for r in rows:
        i = int(r["id"])
        if want and i not in want:
            continue
        ref = r["ref"].strip()
        cmd = [exe, "generate", "create", "flow-text-to-image" if ref == "-" else "flow-image-to-image",
               "--model", MODEL, "--aspect-ratio", "1:1", "--outputs", "1",
               "--batch", os.environ.get("STICK_BATCH", "4"), "--index", str(i), "--folder", folder() + "_el"]
        prompt = r["object"].strip()
        if ref != "-":
            cmd += ["--image", "img/sheet.jpg" if ref == "sheet" else f"img/ref_{ref}.jpg"]
            prompt += FIX
        if "--dry" in a:
            print(" ".join(cmd[1:])); n += 1; continue
        res = subprocess.run(cmd + ["--prompt", prompt + EL_PROMPT], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        print(f"element {i:02d}: {(res.stdout or res.stderr).strip()[:60]}")
        n += 1
    print(f"{n} elements submitted to folder {folder()}_el")


def cutouts(a):
    global folder
    base = folder
    folder = lambda: base() + "_el"                       # noqa: E731  (same finder, element folder)
    fs = files()
    swap = {}
    if os.path.exists("ELPICK.tsv"):
        for r in csv.DictReader(open("ELPICK.tsv", encoding="utf-8"), delimiter="	"):
            swap[int(r["shot"])] = int(r["file"])
    os.makedirs("elements/raw", exist_ok=True)
    rows = list(csv.DictReader(open("ELEMENTS.tsv", encoding="utf-8"), delimiter="	"))
    for r in rows:
        i = int(r["id"]); f = swap.get(i, i)
        if f in fs:
            im = Image.open(fs[f][0]).convert("RGB")
            px = im.load(); w, h = im.size
            bg = px[4, 4]
            ImageDraw.Draw(im).rectangle((w - int(w * 0.12), h - int(h * 0.12), w, h), fill=bg)  # Flow sparkle
            im.save(f"elements/raw/{i:02d}.png")
        else:
            print("missing element", i)
    keyer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.py")
    res = subprocess.run([sys.executable, keyer, "elements/raw", "elements/cut"], capture_output=True, text=True)
    print((res.stdout or res.stderr).strip()[-600:])
    ps = sorted(glob.glob("elements/cut/*.png"))
    if ps:                                              # checkerboard-free preview on grey
        g = []
        for p in ps:
            im = Image.open(p).convert("RGBA")
            t = Image.new("RGBA", im.size, (150, 150, 150, 255)); t.alpha_composite(im); g.append(t)
        tmp = []
        for k, t in enumerate(g):
            q = f"elements/_prev{k}.png"; t.convert("RGB").save(q); tmp.append(q)
        grid(tmp, [os.path.basename(p)[:2] for p in ps], "cutouts.jpg", 300, 300, 6)
        for q in tmp:
            os.remove(q)


if __name__ == "__main__":
    cmds = {"refs": refs, "submit": submit, "review": review, "pick": pick, "qc": qc,
            "elements": elements, "cutouts": cutouts}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](sys.argv[2:])
