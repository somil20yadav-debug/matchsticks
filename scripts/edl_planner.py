"""Deterministic, seed-driven EDL (Edit Decision List) Planner.
Generates style_profile.json and edl.json from SCENES.tsv, WORDS.tsv, and STYLE.txt.
Guarantees determinism via PCG64 with per-scene RNG substreams.
"""
import argparse, csv, hashlib, json, math, os, re, sys, tempfile
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import W, H, FPS, LOOKS, set_look, card, picture, busy, sticker, tag_image

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "in", "on", "at",
    "to", "for", "with", "by", "of", "that", "this", "it", "they", "them", "their",
    "you", "your", "he", "she", "his", "her", "we", "our", "us", "from", "as", "be"
}

NUMERIC_RE = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred|thousand|million|billion)\b", re.I)
SUPERLATIVE_RE = re.compile(r"\b(first|last|oldest|deepest|furthest|highest|longest|most|never|impossible|only|extreme|greatest|massive|giant)\b", re.I)
NEGATION_RE = re.compile(r"\b(not|no|never|none|without|cannot|against|instead|before)\b", re.I)

def score_word(word_str, is_line_final=False):
    """Exact word scoring weights:
    Numbers / Quantities: 1.0
    Superlatives / Extremes: 0.9
    Negations / Contrasts: 0.8
    Capitalized Proper Nouns: 0.7
    Sentence / Line-final words: 0.6
    All other words: 0.0 (disqualified, minimum threshold = 0.6)
    """
    clean_w = re.sub(r"[^\w]", "", word_str).strip()
    if not clean_w or clean_w.lower() in STOP_WORDS:
        return 0.0
    if NUMERIC_RE.search(clean_w):
        return 1.0
    if SUPERLATIVE_RE.search(clean_w):
        return 0.9
    if NEGATION_RE.search(clean_w):
        return 0.8
    if clean_w[0].isupper() and len(clean_w) > 2:
        return 0.7
    if is_line_final:
        return 0.6
    return 0.0  # Disqualify weak/ordinary words (strict 0.6 minimum)

def plan_punch_ins_and_shakes(scenes, words_list, rng, total_dur):
    """Plans punch-ins with jittered 6-10s gap, strict 0.5s exclusion zones,
    minimum score threshold of 0.6, and maximum density cap of 1 per 8s on average.
    Plans camera shake for tense-tagged scenes (amplitude <= 0.4% frame width, t >= 3.0s).
    """
    all_cuts = [s["t0"] for s in scenes] + [total_dur]
    all_pops = [o["t"] for s in scenes for o in s["ov"]]
    
    # Strict exclusion check: no cut or sticker pop within 0.5s of start, end, or inside the punch-in duration
    def is_in_exclusion_zone(t, dur=1.2):
        if t < 3.0 or (t + dur) > total_dur:
            return True
        t_start = t - 0.5
        t_end = t + dur + 0.5
        for c in all_cuts:
            if t_start <= c <= t_end:
                return True
        for p in all_pops:
            if t_start <= p <= t_end:
                return True
        return False

    # Collect scored candidate words (strictly score >= 0.6)
    scored_candidates = []
    for idx, w in enumerate(words_list):
        t_start = float(w["start"])
        t_end = float(w["end"])
        if t_start < 3.0:
            continue
        is_final = (idx + 1 == len(words_list)) or (words_list[idx + 1]["line"] != w["line"])
        sc = score_word(w["word"], is_line_final=is_final)
        if sc >= 0.6:  # Strict minimum score of 0.6
            scored_candidates.append({
                "word": w["word"],
                "cue": f"{w['line']}.{w['i']}",
                "start": t_start,
                "end": t_end,
                "score": sc
            })

    # Schedule punch-ins with jittered 6-10s gap and density cap (<= 1 per 8s)
    punch_ins = []
    t_cursor = 3.0
    while t_cursor < total_dur - 4.0:
        gap = float(rng.uniform(6.0, 10.0))
        target_t = t_cursor + gap
        window_start = t_cursor + 6.0
        window_end = min(total_dur - 1.5, t_cursor + 10.0)
        
        # Eligible candidates in [window_start, window_end] with score >= 0.6
        # Mathematically guarantees strictly >= 0.500s clean margin to ALL past and future cuts/pops
        valid_cands = []
        for c in scored_candidates:
            if not (window_start <= c["start"] <= window_end):
                continue
            past_evs = [ev for ev in (all_cuts + all_pops) if ev <= c["start"]]
            prev_ev = max(past_evs) if past_evs else 0.0
            if (c["start"] - prev_ev) < 0.505:
                continue

            future_evs = [ev for ev in (all_cuts + all_pops) if ev > c["start"]]
            if not future_evs:
                continue
            next_ev = min(future_evs)
            avail_room = (next_ev - 0.505) - c["start"]
            if avail_room >= 1.0:
                valid_cands.append((c, avail_room))
        
        # Density cap check: max 1 punch-in per 8.0s on average
        max_allowed_count = int(window_end / 8.0)
        if len(punch_ins) >= max_allowed_count:
            # Density exceeded: stretch cursor forward
            t_cursor = window_end
            continue

        if valid_cands:
            # Pick highest score, break ties by proximity to target_t
            valid_cands.sort(key=lambda item: (item[0]["score"], -abs(item[0]["start"] - target_t)), reverse=True)
            chosen, max_room = valid_cands[0]
            target_dur = float(rng.uniform(1.2, 1.5))
            dur = round(min(target_dur, max_room - 0.01), 2)
            punch_ins.append({
                "word": chosen["word"],
                "score": chosen["score"],
                "cue": chosen["cue"],
                "t_in": round(chosen["start"], 3),
                "t_out": round(chosen["start"] + dur, 3),
                "duration": dur,
                "zoom": round(float(rng.uniform(1.04, 1.07)), 3),
                "easing": "easeOutQuad"
            })
            t_cursor = chosen["start"] + dur
        else:
            # No qualifying word (score >= 0.6) exists in window: skip punch-in and advance cursor
            next_disruptions = [t for t in (all_cuts + all_pops) if t > t_cursor + 3.0]
            if next_disruptions:
                t_cursor = min(next_disruptions)
            else:
                t_cursor = window_end

    # Plan camera shake on tense scenes (amplitude <= 0.4% frame width = 7.68 px, t >= 3.0s)
    shakes = []
    for sc in scenes:
        extra_val = sc["row"][4].lower() if len(sc["row"]) > 4 else ""
        text_val = sc["row"][2].lower() if len(sc["row"]) > 2 else ""
        is_tense = ("tense" in extra_val) or ("tense" in text_val) or (sc.get("mood") == "tense")
        if is_tense and sc["t0"] >= 3.0:
            shake_amp_pct = round(float(rng.uniform(0.002, 0.0038)), 4)  # <= 0.4%
            shakes.append({
                "scene_idx": sc.get("scene_idx", 0),
                "t_in": sc["t0"],
                "t_out": sc["t1"],
                "amplitude_pct": shake_amp_pct,
                "freq1": round(float(rng.uniform(0.6, 0.9)), 2),
                "freq2": round(float(rng.uniform(1.2, 1.6)), 2),
                "phase_x": round(float(rng.uniform(0, 2 * math.pi)), 3),
                "phase_y": round(float(rng.uniform(0, 2 * math.pi)), 3)
            })

    return punch_ins, shakes

    return punch_ins, shakes

def get_project_id(project_dir):
    return os.path.basename(os.path.abspath(project_dir)).lower()

def make_seed_int(project_id, seed_val):
    raw = f"{project_id}_{seed_val}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")

def generate_style_profile(project_dir, seed_val, out_path="style_profile.json"):
    proj_id = get_project_id(project_dir)
    seed_int = make_seed_int(proj_id, seed_val)
    rng = np.random.default_rng(np.random.PCG64(seed_int))

    profile = {
        "seed": seed_val,
        "project_id": proj_id,
        "effect_weights": {
            "ken_burns": float(rng.uniform(0.40, 0.60)),
            "punch_in": float(rng.uniform(0.20, 0.35)),
            "camera_shake": float(rng.uniform(0.05, 0.12)),
            "static": float(rng.uniform(0.05, 0.15))
        },
        "motion_speed_range": {
            "zoom_min": 1.02,
            "zoom_max": round(float(rng.uniform(1.04, 1.07)), 3),
            "pan_max_pct": round(float(rng.uniform(0.02, 0.04)), 3)
        },
        "easing_set": ["easeInOutCubic", "easeInOutSine", "easeOutQuad"],
        "transitions": ["cut", "whip_pan", "zoom_through"],
        "punch_in_density_sec": [6.0, 10.0],
        "safe_zones": {
            "margin_x": 0.08,
            "margin_y": 0.08
        }
    }
    # Normalize weights
    total_w = sum(profile["effect_weights"].values())
    for k in profile["effect_weights"]:
        profile["effect_weights"][k] = round(profile["effect_weights"][k] / total_w, 3)

    target = os.path.join(project_dir, out_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix="profile_", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    os.replace(tmp_path, target)
    return profile

def extent(o, H_ref=H, project_dir="."):
    hh = int(o["h"] * H_ref)
    if o["img"] == "count":
        num, _, cap = o["text"].partition("|")
        im = tag_image(f"{float(num.replace(',', '')):,.0f}" + (f"|{cap}" if cap else ""), max(50, hh // 4))
        return im.width, im.height, 0
    if o["img"] == "tag":
        im = tag_image(o["text"], max(46, hh // 4))
        return im.width, im.height, 0
    if o["img"].startswith("peek:"):
        from mascot import get_mascot_image
        parts = o["img"].split(":")
        corner = parts[1] if len(parts) > 1 else "bl"
        pose = parts[2] if len(parts) > 2 else "curious"
        st = get_mascot_image(pose=pose, corner=corner, target_h=hh)
        return st.width, st.height, 0
    st_path = o["img"] if os.path.isabs(o["img"]) else os.path.join(project_dir, o["img"])
    st = sticker(st_path, hh, o.get("plain", False))
    if not o["text"]:
        return st.width, st.height, 0
    tg = tag_image(o["text"], 60)
    w, h = max(st.width, tg.width), st.height + tg.height - 10
    return w, h, (tg.height - 10) / 2

def autoplace_scene(sc, space_map, project_dir="."):
    todo = [o for o in sc["ov"] if o["x"] is None]
    if not todo:
        return
    img = sc["row"][1].strip()
    if img == "card":
        pic = card()
    else:
        pic_path = img if os.path.isabs(img) else os.path.join(project_dir, img)
        pic = picture(pic_path) if os.path.exists(pic_path) else card()
    e = busy(pic)
    side = space_map.get(os.path.splitext(os.path.basename(img))[0])
    if img != "card":
        a = np.asarray(pic.resize((W // 8, H // 8)), np.int16)
        white = (a.min(axis=2) > 232) & (a.max(axis=2) - a.min(axis=2) < 14)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        skin = (r > 185) & (g > 140) & (b > 100) & (r > g) & (g > b) & (r - b > 35) & (r - b < 105)
        e = e + white * 60.0 + skin * 40.0
    taken = [(o["x"], o["y"], o["h"]) for o in sc["ov"] if o["x"] is not None]
    spots = [(0.86, 0.2), (0.14, 0.2), (0.86, 0.78), (0.14, 0.78), (0.5, 0.16),
             (0.76, 0.3), (0.24, 0.3), (0.78, 0.62), (0.22, 0.62), (0.5, 0.84)]
    if side == "top":
        spots = [(0.3, 0.2), (0.7, 0.2), (0.5, 0.17), (0.16, 0.2), (0.84, 0.2)]
    elif side:
        xs = (0.8, 0.86) if side == "right" else (0.2, 0.14)
        spots = [(xs[0], 0.3), (xs[0], 0.62), (xs[1], 0.18), (xs[1], 0.8), (xs[0], 0.46)]
    for o in todo:
        if o["img"].startswith("peek:"):
            parts = o["img"].split(":")
            corner = parts[1] if len(parts) > 1 else "bl"
            if corner == "br":
                o["x"], o["y"] = 0.86, 0.76
            elif corner == "left-edge":
                o["x"], o["y"] = 0.14, 0.50
            else:
                o["x"], o["y"] = 0.14, 0.76
            taken.append((o["x"], o["y"], o["h"]))
            continue
        hh = o["h"] * H
        ww = hh * 1.1
        def cost(i, xy):
            x0, y0 = xy[0] * W - ww / 2, xy[1] * H - hh / 2
            for tx, ty, th in taken:
                if abs(tx - xy[0]) * W < (ww + th * H * 1.1) / 2 and abs(ty - xy[1]) * H < (hh + th * H) / 2:
                    return 1e9
            m = e[max(0, int(y0) // 8):int(y0 + hh) // 8, max(0, int(x0) // 8):int(x0 + ww) // 8]
            centre = 1 + 1.2 * np.exp(-((xy[0] - 0.5) ** 2 / 0.05 + (xy[1] - 0.55) ** 2 / 0.08))
            return float(m.mean()) * centre * (1 + 0.03 * i) if m.size else 1e9
        o["x"], o["y"] = min(spots, key=lambda xy: cost(spots.index(xy), xy))
        taken.append((o["x"], o["y"], o["h"]))

def separate_scene(sc, project_dir="."):
    ov = sc["ov"]
    for _ in range(12):
        boxes = []
        for o in ov:
            w, h, dy = extent(o, project_dir=project_dir)
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
        for o, bx in zip(ov, boxes):
            half = bx[2] / 2 / W
            o["x"] = min(max(o["x"], half + 0.02), 1 - half - 0.02)
        if not moved:
            return
        for o in ov:
            o["h"] *= 0.94

def build_edl(project_dir, seed_val=42, motion=False, parallax=False, out_path="edl.json"):
    project_dir = os.path.abspath(project_dir)
    profile_path = os.path.join(project_dir, "style_profile.json")
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    else:
        profile = generate_style_profile(project_dir, seed_val)

    words_file = os.path.join(project_dir, "WORDS.tsv")
    scenes_file = os.path.join(project_dir, "SCENES.tsv")
    shots_file = os.path.join(project_dir, "SHOTS.tsv")

    words = {f"{r['line']}.{r['i']}": max(0.0, float(r["start"]))
             for r in csv.DictReader(open(words_file, encoding="utf-8"), delimiter="\t")}
    
    rows = [r for r in csv.reader(open(scenes_file, encoding="utf-8"), delimiter="\t")
            if r and r[0].strip() and not r[0].startswith("#") and r[0] != "cue"]

    space_map = {}
    flip_set = set()
    if os.path.exists(shots_file):
        for r in csv.DictReader(open(shots_file, encoding="utf-8"), delimiter="\t"):
            sid = f"s{int(r['id']):02d}"
            if (r.get("space") or "").strip().lower() in ("left", "right", "top"):
                space_map[sid] = r["space"].strip().lower()
            if (r.get("flip") or "").strip().lower() in ("yes", "y", "1", "true"):
                flip_set.add(sid)

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
                                         x=x, y=y, h=h, motion=mo.replace("+x", "") or "pop",
                                         cross="+x" in mo, plain=plain, cue=c))
        else:
            if cue not in words:
                sys.exit(f"cue {cue} is not a line.word in WORDS.tsv")
            scenes.append(dict(t0=words[cue] if scenes else 0.0, row=r, ov=[], cue=cue))

    # Read total duration
    import subprocess
    audio_path = os.path.join(project_dir, "mix.wav" if os.path.exists(os.path.join(project_dir, "mix.wav")) else "VO.wav")
    total_dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                      "-of", "csv=p=0", audio_path], capture_output=True, text=True).stdout)

    for a, b in zip(scenes, scenes[1:]):
        a["t1"] = b["t0"]
    scenes[-1]["t1"] = total_dur

    # Run autoplace and separation
    for sc in scenes:
        autoplace_scene(sc, space_map, project_dir)
        separate_scene(sc, project_dir)

    # Master RNG with per-scene substreams
    proj_id = get_project_id(project_dir)
    master_seed = make_seed_int(proj_id, seed_val)
    root_rng = np.random.default_rng(np.random.PCG64(master_seed))
    scene_rngs = root_rng.spawn(len(scenes))

    words_list = list(csv.DictReader(open(words_file, encoding="utf-8"), delimiter="\t"))
    punch_ins, shakes = ([], []) if not motion else plan_punch_ins_and_shakes(scenes, words_list, root_rng, total_dur)

    edl_scenes = []
    last_effect = None

    for idx, (sc, s_rng) in enumerate(zip(scenes, scene_rngs)):
        _, img, text, pos, extra = [x.strip() for x in sc["row"][:5]]
        dur = sc["t1"] - sc["t0"]

        if not motion:
            base_effect = {
                "type": "static",
                "zoom_start": 1.0,
                "zoom_end": 1.0,
                "pan_x": 0.0,
                "pan_y": 0.0,
                "easing": "linear"
            }
        else:
            # Check if this scene has an active punch-in: rule: NEVER combine Ken Burns and punch-in in the same scene
            scene_has_punch_in = any(
                max(sc["t0"], pi["t_in"]) < min(sc["t1"], pi["t_out"])
                for pi in punch_ins
            )

            # Ken Burns capped at <= 35-40% of scenes; never on scenes with punch-ins, never on short cuts (< 2.2s)
            allow_ken_burns = (
                (not scene_has_punch_in)
                and (dur >= 2.2)
                and (last_effect != "ken_burns")
                and (float(s_rng.uniform(0.0, 1.0)) < 0.35)
            )

            if not allow_ken_burns:
                base_effect = {
                    "type": "static",
                    "zoom_start": 1.0,
                    "zoom_end": 1.0,
                    "pan_x": 0.0,
                    "pan_y": 0.0,
                    "easing": "linear"
                }
                last_effect = "static"
            else:
                last_effect = "ken_burns"
                # Very slow, subtle motion: <= 2.5% zoom over entire scene, pan <= 0.5% width (<= 9.6 px total)
                kb_mode = s_rng.choice(["slow_push", "slow_pull", "drift_left", "drift_right"])
                pan_subtle = round(float(s_rng.uniform(0.002, 0.005)), 4)  # <= 0.5% width
                
                if kb_mode == "slow_push":
                    base_effect = {
                        "type": "ken_burns",
                        "zoom_start": 1.0,
                        "zoom_end": round(float(s_rng.uniform(1.020, 1.028)), 3), # <= 2.8% zoom
                        "pan_x": 0.0,
                        "pan_y": 0.0,
                        "easing": "easeInOutSine"
                    }
                elif kb_mode == "slow_pull":
                    base_effect = {
                        "type": "ken_burns",
                        "zoom_start": round(float(s_rng.uniform(1.020, 1.028)), 3),
                        "zoom_end": 1.0,
                        "pan_x": 0.0,
                        "pan_y": 0.0,
                        "easing": "easeInOutSine"
                    }
                elif kb_mode == "drift_left":
                    base_effect = {
                        "type": "ken_burns",
                        "zoom_start": 1.015,
                        "zoom_end": 1.015,
                        "pan_x": -pan_subtle,
                        "pan_y": 0.0,
                        "easing": "linear"
                    }
                else:
                    base_effect = {
                        "type": "ken_burns",
                        "zoom_start": 1.015,
                        "zoom_end": 1.015,
                        "pan_x": pan_subtle,
                        "pan_y": 0.0,
                        "easing": "linear"
                    }

        # Determine parallax move (script syntax or global flag)
        explicit_parallax = None
        for tok in extra.split():
            if tok.startswith("parallax:"):
                explicit_parallax = tok.split(":", 1)[1].strip()

        parallax_move = None
        if explicit_parallax == "off":
            parallax_move = None
        elif explicit_parallax in ("push", "pull", "driftL", "driftR", "orbit"):
            if dur >= 3.0 and img != "card":
                parallax_move = explicit_parallax
        elif parallax and img != "card" and dur >= 3.0:
            parallax_move = str(s_rng.choice(["push", "pull", "driftL", "driftR", "orbit"]))

        if parallax_move:
            base_effect = {
                "type": "parallax",
                "move": parallax_move,
                "easing": "easeInOutCubic"
            }
            last_effect = "parallax"

        edl_sc = {
            "scene_idx": idx,
            "cue": sc["cue"],
            "t0": round(sc["t0"], 3),
            "t1": round(sc["t1"], 3),
            "duration": round(dur, 3),
            "img": img,
            "text": text,
            "pos": pos,
            "extra": extra,
            "base_effect": base_effect,
            "parallax_effect": {"move": parallax_move} if parallax_move else None,
            "overlays": [
                {
                    "cue": o["cue"],
                    "t": round(o["t"], 3),
                    "img": o["img"],
                    "text": o["text"],
                    "x": round(float(o["x"]), 4),
                    "y": round(float(o["y"]), 4),
                    "h": round(float(o["h"]), 4),
                    "motion": o["motion"],
                    "plain": o["plain"],
                    "cross": o["cross"]
                }
                for o in sc["ov"]
            ]
        }
        edl_scenes.append(edl_sc)

    edl = {
        "project_id": proj_id,
        "seed": seed_val,
        "motion": motion,
        "parallax": parallax,
        "fps": FPS,
        "total_duration": round(total_dur, 3),
        "canvas_size": [W, H],
        "oversample": 1.25 if motion else 1.0,
        "punch_ins": punch_ins,
        "camera_shakes": shakes,
        "scenes": edl_scenes
    }

    target = os.path.join(project_dir, out_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix="edl_", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(edl, f, indent=2)
    os.replace(tmp_path, target)
    return edl

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--motion", choices=["on", "off"], default="off")
    ap.add_argument("--parallax", choices=["on", "off"], default="off")
    ap.add_argument("--out", default="edl.json")
    args = ap.parse_args()
    build_edl(args.project, args.seed, motion=(args.motion == "on"), parallax=(args.parallax == "on"), out_path=args.out)
    print(f"EDL built successfully: {args.out}")
