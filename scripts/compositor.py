"""Deterministic Oversampled Video Compositor.
Consumes edl.json and media assets, executes geometric transformations,
composites overlays, and pipes rgb24 frames to ffmpeg stdin.
Format consistency: RGB24 end-to-end.
"""
import argparse, json, math, os, shutil, subprocess, sys
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import (
    W, H, FPS, CHART, LOOKS, set_look,
    card, picture, label, bars, sticker, tag_image, place, cross_layer, ease_back
)

def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    env_bin = os.environ.get("FFMPEG_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    winget_paths = [
        r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
    ]
    for p in winget_paths:
        if os.path.exists(p):
            return p
    return "ffmpeg"

def ease_in_out_cubic(p):
    p = max(0.0, min(1.0, p))
    return 4 * p * p * p if p < 0.5 else 1 - math.pow(-2 * p + 2, 3) / 2

def ease_in_out_sine(p):
    p = max(0.0, min(1.0, p))
    return -(math.cos(math.pi * p) - 1) / 2

def ease_out_quad(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) * (1 - p)

EASING_MAP = {
    "linear": lambda p: max(0.0, min(1.0, p)),
    "easeInOutCubic": ease_in_out_cubic,
    "easeInOutSine": ease_in_out_sine,
    "easeOutQuad": ease_out_quad
}

def render_base_scene(sc_edl, project_dir):
    img = sc_edl["img"]
    text = sc_edl["text"]
    pos = sc_edl["pos"]
    extra = sc_edl["extra"]

    if img == "card":
        fr = card()
    else:
        pic_path = img if os.path.isabs(img) else os.path.join(project_dir, img)
        fr = picture(pic_path)

    blocked = []
    if extra.startswith("bars:"):
        bars(fr, extra[5:])
        blocked.append(CHART)

    for o in sc_edl.get("overlays", []):
        hh = o["h"] * H
        ww = hh * 1.2
        blocked.append((o["x"] * W - ww / 2, o["y"] * H - hh / 2, o["x"] * W + ww / 2, o["y"] * H + hh / 2))

    if text:
        label(fr, text, "big" if img == "card" else (pos if pos.endswith("!") else "auto"), blocked)

    return fr.convert("RGBA")

def apply_camera_motion(base_arr_rgb, base_effect, t_in_scene, duration, oversample=1.25, active_punch_in=None, active_shake=None, t_master=0.0):
    """Applies camera transform (Ken Burns, punch-in, smooth camera shake) using cv2.warpAffine on RGB24 array.
    Guarantees zoom capped at 1.10, shake amplitude <= 0.4% frame width, and INTER_CUBIC downscaling.
    """
    is_static = (base_effect.get("type") == "static" or duration <= 0)
    has_motion = (not is_static) or (active_punch_in is not None) or (active_shake is not None)
    if not has_motion:
        return base_arr_rgb

    # 1. Base Ken Burns motion
    if is_static:
        z_base = 1.0
        px_base = 0.0
        py_base = 0.0
    else:
        p = max(0.0, min(1.0, t_in_scene / duration))
        easing_fn = EASING_MAP.get(base_effect.get("easing", "linear"), ease_in_out_cubic)
        eased_p = easing_fn(p)
        z0 = float(base_effect.get("zoom_start", 1.0))
        z1 = float(base_effect.get("zoom_end", 1.0))
        z_base = z0 + (z1 - z0) * eased_p
        px_base = float(base_effect.get("pan_x", 0.0)) * eased_p
        py_base = float(base_effect.get("pan_y", 0.0)) * eased_p

    # 2. Punch-in calculation
    z_punch = 1.0
    if active_punch_in:
        t_in = active_punch_in["t_in"]
        t_out = active_punch_in["t_out"]
        p_dur = t_out - t_in
        if 0 <= t_master - t_in <= p_dur:
            dt = t_master - t_in
            # Snap in over 0.25s
            if dt < 0.25:
                prog = ease_out_quad(dt / 0.25)
            # Ease out over final 0.3s
            elif dt > p_dur - 0.3:
                prog = ease_in_out_cubic(max(0.0, (t_out - t_master) / 0.3))
            else:
                prog = 1.0
            target_zoom = float(active_punch_in.get("zoom", 1.06))
            z_punch = 1.0 + (target_zoom - 1.0) * prog

    # Combine zoom, strictly capped at 1.07 to prevent stroke softening
    z_final = min(1.07, z_base * z_punch)

    # 3. Camera shake calculation (smooth multi-octave sine noise, <= 0.4% frame width)
    shake_dx = 0.0
    shake_dy = 0.0
    if active_shake and t_master >= 3.0:
        s_in = active_shake["t_in"]
        s_out = active_shake["t_out"]
        s_dur = max(0.1, s_out - s_in)
        dt_s = t_master - s_in
        # Smooth envelope (0.3s ramp-in, 0.3s ramp-out)
        env = 1.0
        if dt_s < 0.3:
            env = dt_s / 0.3
        elif dt_s > s_dur - 0.3:
            env = max(0.0, (s_out - t_master) / 0.3)
        
        amp_pct = min(0.004, float(active_shake.get("amplitude_pct", 0.003)))
        max_px = amp_pct * W
        f1 = float(active_shake.get("freq1", 0.8))
        f2 = float(active_shake.get("freq2", 1.4))
        ph_x = float(active_shake.get("phase_x", 0.0))
        ph_y = float(active_shake.get("phase_y", 1.0))

        # Sum of 2 non-harmonic octaves for organic smooth camera tremor
        wave_x = 0.7 * math.sin(2 * math.pi * f1 * t_master + ph_x) + 0.3 * math.sin(2 * math.pi * f2 * t_master + ph_x)
        wave_y = 0.7 * math.sin(2 * math.pi * f1 * t_master + ph_y) + 0.3 * math.sin(2 * math.pi * f2 * t_master + ph_y)
        shake_dx = max_px * wave_x * env
        shake_dy = (max_px * 0.6) * wave_y * env

    # Center coordinates & affine matrix
    cx, cy = W / 2.0, H / 2.0
    shift_x = (px_base * W) + shake_dx
    shift_y = (py_base * H) + shake_dy

    # Identity transform optimization: return base array directly without any resampling
    if abs(z_final - 1.0) < 1e-4 and abs(shift_x) < 1e-3 and abs(shift_y) < 1e-3:
        return base_arr_rgb

    M = np.array([
        [z_final, 0.0, (1.0 - z_final) * cx + shift_x],
        [0.0, z_final, (1.0 - z_final) * cy + shift_y]
    ], dtype=np.float32)

    return cv2.warpAffine(base_arr_rgb, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

def render_edl(edl_path, audio_path, out_mp4, draft=False, broll_file=None, font="anton", style="minimal"):
    edl_path = os.path.abspath(edl_path)
    project_dir = os.path.dirname(edl_path)
    with open(edl_path, "r", encoding="utf-8") as f:
        edl = json.load(f)

    # Set look from STYLE.txt if available
    style_txt = os.path.join(project_dir, "STYLE.txt")
    if os.path.exists(style_txt):
        first = open(style_txt, encoding="utf-8").readline()
        if first.lower().startswith("look:"):
            look = first.split(":", 1)[1].strip()
            if look in LOOKS:
                set_look(look)

    scenes = edl["scenes"]
    total = float(edl["total_duration"])
    motion_enabled = edl.get("motion", False)
    oversample = float(edl.get("oversample", 1.25))
    punch_ins = edl.get("punch_ins", [])
    camera_shakes = edl.get("camera_shakes", [])

    broll_entries = []
    if broll_file:
        b_path = broll_file if os.path.isabs(broll_file) else os.path.join(project_dir, broll_file)
        if os.path.exists(b_path):
            with open(b_path, "r", encoding="utf-8") as f:
                broll_entries = json.load(f)

    # Parallax preparation and tracking
    parallax_enabled = edl.get("parallax", False)
    parallax_scenes = {}
    parallax_report = {
        "active_scenes": [],
        "move_counts": {},
        "fallbacks": [],
        "cache_hits": 0,
        "cache_misses": 0
    }

    if parallax_enabled:
        from depth_parallax import get_or_create_parallax_layers
        from parallax_compositor import render_parallax_frame
        cache_dir = os.path.join(project_dir, "img", "parallax_cache")

        for idx, sc in enumerate(scenes):
            pe = sc.get("parallax_effect")
            if not pe:
                continue
            dur = sc["duration"]
            img = sc["img"]
            cue = sc["cue"]

            # Guardrail: Never apply on scenes shorter than 3s or text cards
            if dur < 3.0 or img == "card":
                reason = "scene shorter than 3s" if dur < 3.0 else "text card"
                print(f"[PARALLAX FALLBACK] Scene {cue}: {reason}. Falling back to Ken Burns.")
                parallax_report["fallbacks"].append({"cue": cue, "reason": reason})
                continue

            pic_path = img if os.path.isabs(img) else os.path.join(project_dir, img)
            if not os.path.exists(pic_path):
                continue

            try:
                layers, hit, quality = get_or_create_parallax_layers(pic_path, cache_dir=cache_dir)
                if hit:
                    parallax_report["cache_hits"] += 1
                else:
                    parallax_report["cache_misses"] += 1

                # Guardrail: Auto-fallback if depth map is poor
                if not quality.get("valid", True):
                    reason = quality.get("reason", "poor depth quality")
                    print(f"[PARALLAX FALLBACK] Scene {cue}: {reason}. Falling back to Ken Burns.")
                    parallax_report["fallbacks"].append({"cue": cue, "reason": reason})
                    continue

                mv = pe.get("move", "push")
                parallax_scenes[idx] = (layers, mv)
                parallax_report["active_scenes"].append(cue)
                parallax_report["move_counts"][mv] = parallax_report["move_counts"].get(mv, 0) + 1
            except Exception as e:
                print(f"[PARALLAX FALLBACK] Scene {cue}: {e}. Falling back to Ken Burns.")
                parallax_report["fallbacks"].append({"cue": cue, "reason": str(e)})

    # Initialize Anton Word-Synced Caption Engine
    words_tsv = os.path.join(project_dir, "WORDS.tsv")
    caption_engine = None
    if os.path.exists(words_tsv):
        try:
            from caption_renderer import CaptionEngine
            caption_engine = CaptionEngine(words_tsv, font_name=font, style=style, W=W, H=H)
            print(f"Initialized {font.upper()} ({style.upper()}) word-synced caption engine.")
        except Exception as e:
            print(f"Warning: Could not initialize caption engine: {e}")

    render_w, render_h = (W // 2, H // 2) if draft else (W, H)
    ffmpeg_exe = find_ffmpeg()

    frames_dir = os.path.join(project_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.endswith(".png"):
            os.remove(os.path.join(frames_dir, f))

    cmd = [
        ffmpeg_exe, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{render_w}x{render_h}", "-r", str(FPS), "-i", "-",
        "-i", audio_path, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-threads", "3", "-c:a", "aac", "-b:a", "192k",
        "-shortest", out_mp4
    ]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    base_cache = {}
    si = 0
    last_frame_bytes = None

    total_frames = int(total * FPS) + 1
    for fi in range(total_frames):
        t = fi / FPS
        while si + 1 < len(scenes) and t >= scenes[si + 1]["t0"]:
            if last_frame_bytes:
                # Save QC milestone frame
                qc_img = Image.frombytes("RGB", (render_w, render_h), last_frame_bytes)
                qc_img.save(os.path.join(frames_dir, f"{si + 1:03d}.png"))
            si += 1

        sc = scenes[si]
        t_in_scene = t - sc["t0"]
        is_parallax_scene = (si in parallax_scenes)

        # B-roll cutaway check
        active_br = next((b for b in broll_entries if b["t_in"] <= t <= b["t_out"] and b.get("asset")), None)
        if active_br:
            br_asset = active_br["asset"]
            br_path = br_asset if os.path.isabs(br_asset) else os.path.join(project_dir, br_asset)
            if os.path.exists(br_path):
                if br_path.endswith(".png") and "elements" in br_path:
                    fr = card()
                    st = sticker(br_path, int(H * 0.65))
                    fr.alpha_composite(st, ((W - st.width) // 2, (H - st.height) // 2))
                else:
                    fr = picture(br_path).convert("RGBA")
            else:
                fr = base_cache.get(si, render_base_scene(sc, project_dir)).copy()
        elif is_parallax_scene:
            layers, mv = parallax_scenes[si]
            bg_arr = render_parallax_frame(layers, mv, t_in_scene, sc["duration"], W, H)
            fr = Image.fromarray(bg_arr, "RGB").convert("RGBA")
            text = sc.get("text", "")
            pos = sc.get("pos", "")
            extra = sc.get("extra", "")
            blocked = []
            if extra.startswith("bars:"):
                bars(fr, extra[5:])
                blocked.append(CHART)
            for o in sc.get("overlays", []):
                hh = o["h"] * H
                ww = hh * 1.2
                blocked.append((o["x"] * W - ww / 2, o["y"] * H - hh / 2, o["x"] * W + ww / 2, o["y"] * H + hh / 2))
            if text:
                label(fr, text, "big" if sc["img"] == "card" else (pos if pos.endswith("!") else "auto"), blocked)
        else:
            if si not in base_cache:
                base_cache.clear()
                base_cache[si] = render_base_scene(sc, project_dir)
            fr = base_cache[si].copy()

        # Overlays compositing (suppressed during B-roll cutaway or when stickers disabled)
        stickers_enabled = edl.get("stickers", True)
        if stickers_enabled and not active_br:
            from mascot import get_mascot_image
            t_in_scene = t - sc["t0"]
            for o in sc.get("overlays", []):
                dt = t - o["t"]
                if dt < 0:
                    continue
                hh = int(o["h"] * H)

                if o["img"] == "count":
                    p = min(1.0, max(0.0, dt / 0.4))
                    cx, cy = o["x"] * W, o["y"] * H
                    num, _, cap = o["text"].partition("|")
                    target = float(num.replace(",", ""))
                    v = target * (1 - (1 - min(1.0, dt / 0.9)) ** 3)
                    s_num = f"{int(round(v)):,}" if target >= 1000 else str(int(round(v)))
                    place(fr, tag_image(s_num + (f"|{cap}" if cap else ""), max(50, hh // 4)), cx, cy, p, o["motion"])
                elif o["img"] == "tag":
                    p = min(1.0, max(0.0, dt / 0.4))
                    cx, cy = o["x"] * W, o["y"] * H
                    place(fr, tag_image(o["text"], max(46, hh // 4)), cx, cy, p, o["motion"])
                elif o["img"].startswith("peek:"):
                    # Mascot Peek lifecycle: ~1.6s total (anticipation -> spring pop-up -> idle bob -> duck)
                    parts = o["img"].split(":")
                    corner = parts[1] if len(parts) > 1 else "bl"
                    pose = parts[2] if len(parts) > 2 else "curious"

                    if dt > 1.60:
                        continue  # Ducked out

                    st = get_mascot_image(pose=pose, corner=corner, target_h=hh)

                    # Compute 5-phase motion progress
                    if dt < 0.20:
                        # 1. Anticipation (0 - 0.2s): slight tuck
                        p_anim = -0.08 * (dt / 0.20)
                        tilt = 0
                    elif dt < 0.55:
                        # 2. Spring pop-up with overshoot (0.2 - 0.55s)
                        p_norm = (dt - 0.20) / 0.35
                        p_anim = ease_back(p_norm)
                        lean_max = -10 if corner == "br" else 10
                        tilt = lean_max * p_norm
                    elif dt < 1.25:
                        # 3. Idle bob (0.55 - 1.25s)
                        p_anim = 1.0 + 0.02 * math.sin(2 * math.pi * 2.0 * (dt - 0.55))
                        tilt = -10 if corner == "br" else 10
                    else:
                        # 4. Duck / exit (1.25 - 1.60s)
                        p_norm = (dt - 1.25) / 0.35
                        p_anim = 1.0 - (p_norm * p_norm)
                        tilt = (-10 if corner == "br" else 10) * (1.0 - p_norm)

                    # Anchor coordinate calculation based on corner
                    if corner == "br":
                        base_x = W - st.width // 2
                        base_y = H - st.height // 2
                        cy = base_y + int((1.0 - p_anim) * (st.height * 0.9))
                        cx = base_x
                    elif corner == "left-edge":
                        base_x = st.width // 2
                        base_y = H // 2
                        cx = base_x - int((1.0 - p_anim) * (st.width * 0.9))
                        cy = base_y
                    else:  # 'bl'
                        base_x = st.width // 2
                        base_y = H - st.height // 2
                        cy = base_y + int((1.0 - p_anim) * (st.height * 0.9))
                        cx = base_x

                    # Apply rotation tilt lean
                    if abs(tilt) > 0.5:
                        st_rotated = st.rotate(tilt, resample=Image.BICUBIC, expand=True)
                    else:
                        st_rotated = st

                    # Composite onto frame
                    fr.alpha_composite(st_rotated, (int(cx - st_rotated.width / 2), int(cy - st_rotated.height / 2)))

                else:
                    p = min(1.0, max(0.0, dt / 0.4))
                    cx, cy = o["x"] * W, o["y"] * H
                    st_path = o["img"] if os.path.isabs(o["img"]) else os.path.join(project_dir, o["img"])
                    st = sticker(st_path, hh, o.get("plain", False))
                    place(fr, st, cx, cy, p, o["motion"])
                    if o.get("cross") and dt > 0.3:
                        k = min(1.0, (dt - 0.3) / 0.3)
                        cr = cross_layer(st.width, st.height, k)
                        fr.alpha_composite(cr, (int(cx - cr.width / 2), int(cy - cr.height / 2)))
                    if o.get("text"):
                        tg = tag_image(o["text"], 60)
                        place(fr, tg, cx, cy + st.height / 2 + tg.height / 2 - 10, p, o["motion"])

        # Convert to RGB array
        rgb_arr = np.array(fr.convert("RGB"), dtype=np.uint8)

        # Apply motion camera transform if motion enabled
        if motion_enabled:
            active_pi = next((p for p in punch_ins if p["t_in"] <= t <= p["t_out"]), None)
            active_sh = next((s for s in camera_shakes if s["t_in"] <= t <= s["t_out"]), None)
            effect_to_apply = {"type": "static"} if is_parallax_scene else sc.get("base_effect", {})
            rgb_arr = apply_camera_motion(
                rgb_arr, effect_to_apply, t_in_scene, sc["duration"],
                oversample=oversample, active_punch_in=active_pi, active_shake=active_sh, t_master=t
            )

        # Apply Anton word-synced captions
        if caption_engine:
            frame_pil = Image.fromarray(rgb_arr, "RGB")
            frame_pil = caption_engine.render_caption_on_image(frame_pil, t)
            rgb_arr = np.array(frame_pil.convert("RGB"), dtype=np.uint8)

        if draft:
            rgb_arr = cv2.resize(rgb_arr, (render_w, render_h), interpolation=cv2.INTER_AREA)

        if rgb_arr.shape != (render_h, render_w, 3):
            raise ValueError(f"Frame shape mismatch: {rgb_arr.shape} != ({render_h}, {render_w}, 3)")

        last_frame_bytes = rgb_arr.tobytes()
        ff.stdin.write(last_frame_bytes)

    if last_frame_bytes:
        qc_img = Image.frombytes("RGB", (render_w, render_h), last_frame_bytes)
        qc_img.save(os.path.join(frames_dir, f"{len(scenes):03d}.png"))

    ff.stdin.close()
    ff.wait()
    print(f"Rendered {out_mp4} ({total:.1f}s, {len(scenes)} scenes)")

    if parallax_enabled:
        print("\n=== Parallax Render Report ===")
        print(f"  Active Parallax Scenes: {len(parallax_report['active_scenes'])} ({', '.join(parallax_report['active_scenes']) if parallax_report['active_scenes'] else 'None'})")
        print(f"  Move Mix: {json.dumps(parallax_report['move_counts'])}")
        print(f"  Fallbacks: {len(parallax_report['fallbacks'])}")
        for fb in parallax_report['fallbacks']:
            print(f"    - Scene {fb['cue']}: {fb['reason']}")
        total_cache = parallax_report['cache_hits'] + parallax_report['cache_misses']
        hit_rate = (parallax_report['cache_hits'] / total_cache * 100) if total_cache > 0 else 0
        print(f"  Layer Cache: {parallax_report['cache_hits']} hits, {parallax_report['cache_misses']} misses ({hit_rate:.1f}% hit rate)\n")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--edl", default="edl.json")
    ap.add_argument("--audio", default="mix.wav")
    ap.add_argument("--out", default="rendered.mp4")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--font", default="anton")
    ap.add_argument("--style", default="minimal")
    args = ap.parse_args()
    render_edl(args.edl, args.audio, args.out, draft=args.draft, font=args.font, style=args.style)
