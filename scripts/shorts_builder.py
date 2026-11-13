"""Full-Bleed 9:16 Viral Shorts & Reels Engine for StickmanHybrid.
Renders television & mobile-first vertical documentaries (1080x1920):
1. Smart Pan-and-Scan: Follows subject based on composition metadata (no blind center crop).
2. Dynamic Card Renderer: Big glowing typography cards for statistic scenes (zero black frames).
3. 5 Documentary Fonts: 'anton', 'bahnschrift', 'impact', 'segoe', 'consolas'.
4. 4 Caption Styles: 'minimal' (no shadows), 'pill' (dark badge), 'glow' (ambient blur), 'classic'.
5. Audio Sync: Exact slice of mix.wav with smooth fade-in/fade-out.

Usage:
    python scripts/shorts_builder.py <slug> [--start 0.0] [--duration 15.0] [--name short_hook] [--font anton] [--style minimal]
"""

import csv, glob, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.io import wavfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.append(SCRIPTS_DIR)

from caption_renderer import CaptionEngine, resolve_font


def slice_audio(mix_path, out_slice_path, start_t, duration_t):
    """Slices a section of mix.wav and applies audio fades."""
    fs, data = wavfile.read(mix_path)
    start_sample = int(start_t * fs)
    end_sample = min(start_sample + int(duration_t * fs), len(data))
    chunk = data[start_sample:end_sample].copy()

    fade_in_len = min(int(fs * 0.15), len(chunk))
    fade_out_len = min(int(fs * 0.4), len(chunk))

    if fade_in_len > 0:
        chunk[:fade_in_len] = (chunk[:fade_in_len] * np.linspace(0, 1, fade_in_len)[:, None] if chunk.ndim > 1 
                               else chunk[:fade_in_len] * np.linspace(0, 1, fade_in_len))
    if fade_out_len > 0:
        chunk[-fade_out_len:] = (chunk[-fade_out_len:] * np.linspace(1, 0, fade_out_len)[:, None] if chunk.ndim > 1 
                                 else chunk[-fade_out_len:] * np.linspace(1, 0, fade_out_len))

    wavfile.write(out_slice_path, fs, chunk)
    return out_slice_path


def load_shot_composition(project_dir):
    """Reads composition spacing from SHOTS.tsv for smart pan-and-scan."""
    shots_tsv = os.path.join(project_dir, "SHOTS.tsv")
    comp_map = {}
    if os.path.exists(shots_tsv):
        with open(shots_tsv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for r in reader:
                sid = r.get("id", "").strip()
                comp_map[sid] = r.get("space", "center").lower().strip()
    return comp_map


def build_short_video(slug, start_t=0.0, duration=15.0, short_name="short_9x16", font="anton", style="minimal", mode="black", hook_title=None, fps=30):
    project_dir = os.path.join(BASE_DIR, slug)
    if not os.path.exists(project_dir):
        sys.exit(f"[ERROR] Project '{slug}' not found.")

    mix_path = os.path.join(project_dir, "mix.wav")
    if not os.path.exists(mix_path):
        mix_path = os.path.join(project_dir, "VO.wav")
    if not os.path.exists(mix_path):
        sys.exit(f"[ERROR] No audio found in {project_dir}")

    edl_path = os.path.join(project_dir, "edl.json")
    words_path = os.path.join(project_dir, "WORDS.tsv")
    clean_img_dir = os.path.join(project_dir, "img", "clean")
    comp_map = load_shot_composition(project_dir)

    end_t = start_t + duration
    print(f"=== Full-Bleed 9:16 Shorts Engine: Clipping '{slug}' ({start_t:.1f}s - {end_t:.1f}s) ===")
    print(f"    Font: '{font.upper()}' | Caption Style: '{style.upper()}'")

    # 1. Slice Audio
    temp_dir = os.path.join(project_dir, "temp_short")
    os.makedirs(temp_dir, exist_ok=True)
    short_audio_path = os.path.join(temp_dir, "short_audio.wav")
    slice_audio(mix_path, short_audio_path, start_t, duration)
    print(f"[OK] Sliced audio for {duration}s Short.")

    # 2. Match Scenes & Composition
    scenes = []
    last_valid_img = None
    if os.path.exists(edl_path):
        with open(edl_path, "r", encoding="utf-8") as f:
            edl = json.load(f)
        for sc in edl.get("scenes", []):
            sc_t0 = sc.get("t0", 0.0)
            sc_t1 = sc.get("t1", 0.0)
            if sc_t1 >= start_t and sc_t0 <= end_t:
                img_rel = sc.get("img", "")
                is_card = (img_rel.lower() == "card" or not img_rel.startswith("img/"))
                img_path = None
                sid = str(sc.get("scene_idx", 0) + 1)
                space = comp_map.get(sid, "center")

                if not is_card:
                    base = os.path.splitext(os.path.basename(img_rel))[0]
                    cand_png = os.path.join(clean_img_dir, f"{base}.png")
                    cand_jpg = os.path.join(clean_img_dir, f"{base}.jpg")
                    if os.path.exists(cand_png):
                        img_path = cand_png
                    elif os.path.exists(cand_jpg):
                        img_path = cand_jpg
                    elif os.path.exists(os.path.join(project_dir, img_rel)):
                        img_path = os.path.join(project_dir, img_rel)
                    if img_path:
                        last_valid_img = img_path

                cam_move = ""
                if isinstance(sc.get("parallax_effect"), dict):
                    cam_move = sc["parallax_effect"].get("move", "")
                elif isinstance(sc.get("base_effect"), dict):
                    cam_move = sc["base_effect"].get("move", "")

                scenes.append({
                    "t0": sc_t0 - start_t,
                    "t1": sc_t1 - start_t,
                    "is_card": is_card,
                    "img_path": img_path or last_valid_img,
                    "space": space,
                    "cam_move": cam_move,
                    "text": sc.get("text", "")
                })

    if not scenes or not any(s["img_path"] for s in scenes):
        all_stills = sorted(glob.glob(os.path.join(clean_img_dir, "s*.png")) + glob.glob(os.path.join(clean_img_dir, "s*.jpg")))
        fallback_p = all_stills[0] if all_stills else None
        scenes = [{"t0": 0.0, "t1": duration, "is_card": False, "img_path": fallback_p, "space": "center", "cam_move": "", "text": ""}]

    # 3. Setup Caption Engine
    caption_engine = CaptionEngine(words_path, font_name=font, style=style, font_size=58, W=1080, H=1920)
    font_card = resolve_font(font, 84)

    # 4. Render 9:16 Frames
    frames_dir = os.path.join(temp_dir, "frames_9x16")
    os.makedirs(frames_dir, exist_ok=True)

    W, H = 1080, 1920
    total_frames = int(duration * fps)
    print(f"Rendering {total_frames} vertical frames with Smart Pan-and-Scan & {style.upper()} captions...")

    img_cache = {}

    for f_idx in range(total_frames):
        t = f_idx / fps
        active_sc = next((sc for sc in scenes if sc["t0"] <= t < sc["t1"]), scenes[-1])

        # Load background still
        base_img = None
        if active_sc and active_sc["img_path"] and os.path.exists(active_sc["img_path"]):
            p = active_sc["img_path"]
            if p not in img_cache:
                img_cache[p] = Image.open(p).convert("RGB")
            base_img = img_cache[p]
        elif last_valid_img and os.path.exists(last_valid_img):
            if last_valid_img not in img_cache:
                img_cache[last_valid_img] = Image.open(last_valid_img).convert("RGB")
            base_img = img_cache[last_valid_img]
        else:
            base_img = Image.new("RGB", (1920, 1080), (35, 25, 45))

        if mode == "black":
            # -------------------------------------------------------------
            # EXACT 16:9 FRAME ON BLACK BACKGROUND (Zero cropping / cutting)
            # -------------------------------------------------------------
            frame = Image.new("RGB", (W, H), (0, 0, 0))

            vid_w = W  # 1080
            vid_h = int(W * 9 / 16)  # 608
            vid_y = (H - vid_h) // 2  # 656

            # Scale exact 16:9 wide frame untouched
            scaled_16_9 = base_img.resize((vid_w, vid_h), Image.Resampling.LANCZOS)

            # If card scene (e.g. 80,000,000 TREES), render clean typography inside the 16:9 box
            if active_sc.get("is_card") and active_sc.get("text"):
                dim = Image.new("RGBA", (vid_w, vid_h), (5, 8, 15, 175))
                scaled_16_9 = Image.alpha_composite(scaled_16_9.convert("RGBA"), dim).convert("RGB")
                draw_card = ImageDraw.Draw(scaled_16_9)

                raw_text = active_sc["text"].replace("|", "\n").strip()
                lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

                font_num = resolve_font(font, 82)
                font_sub = resolve_font(font, 50)

                if len(lines) == 1:
                    t = lines[0].upper()
                    bb = font_num.getbbox(t)
                    lw = bb[2] - bb[0]
                    draw_card.text(((vid_w - lw) // 2, (vid_h - 90) // 2), t, font=font_num, fill="#FFD02A")
                elif len(lines) >= 2:
                    t1 = lines[0].upper()
                    t2 = " ".join(lines[1:]).upper()
                    bb1 = font_num.getbbox(t1)
                    bb2 = font_sub.getbbox(t2)
                    w1 = bb1[2] - bb1[0]
                    w2 = bb2[2] - bb2[0]
                    y_mid = (vid_h - 140) // 2
                    draw_card.text(((vid_w - w1) // 2, y_mid), t1, font=font_num, fill="#FFD02A")
                    draw_card.text(((vid_w - w2) // 2, y_mid + 85), t2, font=font_sub, fill="#FFFFFF")

            # Paste 16:9 video into black canvas
            frame.paste(scaled_16_9, (0, vid_y))

            # Render Opus Clip Style Top Viral Hook Title (Top black canvas)
            if hook_title:
                draw_top = ImageDraw.Draw(frame)
                font_badge = resolve_font("bahnschrift", 24)
                font_hook = resolve_font(font, 62)
                badge_text = "🔴 THE UNTOLD STORY"
                b_bbox = font_badge.getbbox(badge_text)
                draw_top.text(((W - (b_bbox[2] - b_bbox[0])) // 2, 280), badge_text, font=font_badge, fill="#ff4444")

                h_text = hook_title.upper()
                h_bbox = font_hook.getbbox(h_text)
                draw_top.text(((W - (h_bbox[2] - h_bbox[0])) // 2, 340), h_text, font=font_hook, fill="#FFFFFF")

            # Captions on pure black bottom canvas (y = 1420)
            frame = caption_engine.render_caption_on_image(frame, start_t + t, y_pos=1420)

        else:
            # -------------------------------------------------------------
            # FULL-BLEED SMART PAN-AND-SCAN (Cropped 9:16)
            # -------------------------------------------------------------
            sc_dur = max(active_sc["t1"] - active_sc["t0"], 0.1)
            sc_prog = min(max((t - active_sc["t0"]) / sc_dur, 0.0), 1.0)
            ease_prog = 0.5 - 0.5 * math.cos(sc_prog * math.pi)

            cam_move = active_sc.get("cam_move", "")
            space = active_sc.get("space", "center")

            if cam_move == "driftR":
                pan_center = 0.36 + ease_prog * 0.28
            elif cam_move == "driftL":
                pan_center = 0.64 - ease_prog * 0.28
            elif space == "left":
                pan_center = 0.68 + (ease_prog - 0.5) * 0.05
            elif space == "right":
                pan_center = 0.32 + (ease_prog - 0.5) * 0.05
            else:
                pan_center = 0.50 + math.sin(sc_prog * math.pi) * 0.04

            if cam_move == "push":
                scene_zoom = 1.0 + ease_prog * 0.05
            elif cam_move == "pull":
                scene_zoom = 1.05 - ease_prog * 0.05
            else:
                scene_zoom = 1.0 + ease_prog * 0.02

            scale = max(W / base_img.width, H / base_img.height) * scene_zoom
            nw, nh = int(base_img.width * scale), int(base_img.height * scale)
            scaled_bg = base_img.resize((nw, nh), Image.Resampling.LANCZOS)

            x0 = int((nw - W) * pan_center)
            x0 = max(0, min(x0, nw - W))
            y0 = max(0, min((nh - H) // 2, nh - H))
            frame = scaled_bg.crop((x0, y0, x0 + W, y0 + H))

            if active_sc.get("is_card") and active_sc.get("text"):
                raw_text = active_sc["text"].replace("|", "\n").strip()
                lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
                card_box_w = int(W * 0.90)
                card_box_h = 220
                card_box_x = (W - card_box_w) // 2
                card_box_y = 220

                card_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                co_draw = ImageDraw.Draw(card_overlay)
                co_draw.rounded_rectangle([(card_box_x, card_box_y), (card_box_x + card_box_w, card_box_y + card_box_h)],
                                          radius=18, fill=(10, 14, 24, 215), outline=(56, 139, 253, 220), width=2)
                co_draw.rectangle([(card_box_x + 30, card_box_y + 14), (card_box_x + 90, card_box_y + 18)], fill=(56, 139, 253, 240))
                frame = Image.alpha_composite(frame.convert("RGBA"), card_overlay).convert("RGB")
                draw = ImageDraw.Draw(frame)

                font_tag = resolve_font("bahnschrift", 22)
                draw.text((card_box_x + 30, card_box_y + 26), "// HISTORICAL RECORD ARCHIVE", font=font_tag, fill="#58a6ff")
                font_big = resolve_font(font, 68)
                font_sub = resolve_font(font, 44)
                if len(lines) == 1:
                    draw.text((card_box_x + 30, card_box_y + 80), lines[0].upper(), font=font_big, fill="#FFD02A")
                elif len(lines) >= 2:
                    draw.text((card_box_x + 30, card_box_y + 64), lines[0].upper(), font=font_big, fill="#FFD02A")
                    draw.text((card_box_x + 30, card_box_y + 146), " ".join(lines[1:]).upper(), font=font_sub, fill="#FFFFFF")

            frame = caption_engine.render_caption_on_image(frame, start_t + t, y_pos=1480)

        # Save Frame
        out_f_name = os.path.join(frames_dir, f"frame_{f_idx:05d}.jpg")
        frame.save(out_f_name, quality=92)

    # 5. FFmpeg Stitching to 9:16 MP4 (Saved to clean exports/ folder)
    exports_dir = os.path.join(project_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)
    out_mp4 = os.path.join(exports_dir, f"{short_name}.mp4")
    print(f"Stitching vertical MP4 with FFmpeg -> {out_mp4}...")

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%05d.jpg"),
        "-i", short_audio_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        out_mp4
    ]

    subprocess.run(ffmpeg_cmd, check=True)
    print(f"\n[SUCCESS] Smart Pan-and-Scan 9:16 Short rendered: {out_mp4}")
    print(f"          Font: {font} | Style: {style} | Duration: {duration}s\n")

    # Cleanup temp frames
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    return out_mp4


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/shorts_builder.py <slug> [--start 0.0] [--duration 15.0] [--name short_hook] [--font anton] [--style minimal]")
        sys.exit(1)

    slug = sys.argv[1].lower()
    start_t = 0.0
    duration = 15.0
    name = f"{slug}_short_9x16"
    font = "anton"
    style = "minimal"
    mode = "black"
    hook_title = None

    if "--start" in sys.argv:
        start_t = float(sys.argv[sys.argv.index("--start") + 1])
    if "--duration" in sys.argv:
        duration = float(sys.argv[sys.argv.index("--duration") + 1])
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]
    if "--font" in sys.argv:
        font = sys.argv[sys.argv.index("--font") + 1]
    if "--style" in sys.argv:
        style = sys.argv[sys.argv.index("--style") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--title" in sys.argv:
        hook_title = sys.argv[sys.argv.index("--title") + 1]
    elif "--hook" in sys.argv:
        hook_title = sys.argv[sys.argv.index("--hook") + 1]

    out = build_short_video(slug, start_t=start_t, duration=duration, short_name=name, font=font, style=style, mode=mode, hook_title=hook_title)
    try:
        subprocess.run(["cmd", "/c", "start", "", out])
    except Exception:
        pass


if __name__ == "__main__":
    main()
