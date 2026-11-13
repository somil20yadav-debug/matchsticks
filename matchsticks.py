"""Matchsticks — AI Documentary & Viral Video Production Engine.
Turns ideas and scripts into documentary-grade horizontal videos and 9:16 vertical shorts.

Usage:
    python matchsticks.py story <slug> --topic "Topic description"
    python matchsticks.py voice <slug> [--engine edge|kokoro|eleven]
    python matchsticks.py ingest <slug> [--file VO.wav]
    python matchsticks.py sound <slug>
    python matchsticks.py qc <slug>
    python matchsticks.py render <slug> [--font anton] [--style minimal]
    python matchsticks.py short <slug> [--mode black|crop] [--style minimal]
    python matchsticks.py clip <youtube_url> [--duration 30] [--style minimal]
    python matchsticks.py menu
"""

import csv, glob, json, os, subprocess, sys
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.append(SCRIPTS_DIR)


def print_menu():
    print("""
======================================================================
               MATCHSTICKS — AI VIDEO PRODUCTION ENGINE
======================================================================
  [1] STORY   : python matchsticks.py story <slug> --topic "..."
                (Chops script into 2.5s viral beats, builds SHOTS.tsv & STYLE.txt)

  [2] GENERATE: python matchsticks.py generate <slug> [--provider web|gemini|local|mock]
                (Zero-key free web, Gemini Imagen, local GPU, or offline mock images)

  [3] VOICE   : python matchsticks.py voice <slug> [--engine edge|kokoro|eleven]
                (100% Free Kokoro / Edge-TTS or ElevenLabs voice synthesis)

  [4] INGEST  : python matchsticks.py ingest <slug> [--file VO.wav]
                (Whisper word-level audio alignment -> WORDS.tsv)

  [5] SOUND   : python matchsticks.py sound <slug>
                (Procedural DSP SFX, hits, whooshes & speech ducking -> mix.wav)

  [6] QC      : python matchsticks.py qc <slug>
                (Opens instant zero-render browser scrubbing studio)

  [7] RENDER  : python matchsticks.py render <slug> [--font anton] [--style minimal]
                (Full 1080p longform master render with 3D parallax & captions)

  [8] SHORT   : python matchsticks.py short <slug> [--mode black|crop] [--style minimal]
                (9:16 vertical viral shorts with exact frame & black background)

  [9] CLIP    : python matchsticks.py clip <yt_url> [--duration 30] [--style minimal]
                (AI YouTube Auto-Clipper with Whisper subtitles - Opus Clip)

  5 Available Fonts : 'anton', 'bahnschrift', 'impact', 'segoe', 'consolas'
  4 Caption Styles  : 'minimal' (no shadow), 'pill', 'glow', 'classic'
======================================================================
""")


def init_project(slug):
    project_dir = os.path.join(BASE_DIR, slug)
    for d in ["img", "img/clean", "characters", "elements/cut", "frames", "exports"]:
        os.makedirs(os.path.join(project_dir, d), exist_ok=True)
    return project_dir


def main():
    if len(sys.argv) < 2 or sys.argv[1].lower() in ("menu", "help", "-h", "--help"):
        print_menu()
        sys.exit(0)

    action = sys.argv[1].lower()

    if action == "clip":
        if len(sys.argv) < 3:
            print("Usage: python matchsticks.py clip <youtube_url_or_file> [--duration 30.0] [--font anton] [--style minimal]")
            sys.exit(1)
        clipper_script = os.path.join(SCRIPTS_DIR, "yt_clipper.py")
        cmd = [sys.executable, clipper_script] + sys.argv[2:]
        subprocess.run(cmd)
        return

    if len(sys.argv) < 3:
        print_menu()
        sys.exit(1)

    slug = sys.argv[2].lower()
    project_dir = os.path.join(BASE_DIR, slug)

    if action == "init":
        init_project(slug)
        print(f"[OK] Project '{slug}' initialized at {project_dir}")

    elif action == "story":
        init_project(slug)
        story_script = os.path.join(SCRIPTS_DIR, "story_engine.py")
        cmd = [sys.executable, story_script, slug] + sys.argv[3:]
        subprocess.run(cmd)

    elif action in ("generate", "images", "art"):
        img_script = os.path.join(SCRIPTS_DIR, "image_engine.py")
        cmd = [sys.executable, img_script, slug] + sys.argv[3:]
        subprocess.run(cmd)

    elif action in ("voice", "synthesize"):
        voice_script = os.path.join(SCRIPTS_DIR, "voice_director.py")
        cmd = [sys.executable, voice_script, slug, "--synthesize"] + sys.argv[3:]
        subprocess.run(cmd)

    elif action == "ingest":
        voice_script = os.path.join(SCRIPTS_DIR, "voice_director.py")
        cmd = [sys.executable, voice_script, slug, "--ingest"] + sys.argv[3:]
        subprocess.run(cmd)

    elif action == "sound":
        sound_script = os.path.join(SCRIPTS_DIR, "sound_director.py")
        subprocess.run([sys.executable, sound_script, slug])

    elif action == "qc":
        qc_script = os.path.join(SCRIPTS_DIR, "qc_player_builder.py")
        subprocess.run([sys.executable, qc_script, slug])

    elif action == "render":
        mix_path = os.path.join(project_dir, "mix.wav")
        if not os.path.exists(mix_path):
            print("mix.wav not found. Generating sound effects and ducking mix first...")
            sound_script = os.path.join(SCRIPTS_DIR, "sound_director.py")
            subprocess.run([sys.executable, sound_script, slug])

        exports_dir = os.path.join(project_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        edl_path = os.path.join(project_dir, "edl.json")
        out_mp4 = os.path.join(exports_dir, f"{slug}_master_1080p.mp4")

        font = "anton"
        style = "minimal"
        draft = "--draft" in sys.argv
        if "--font" in sys.argv:
            font = sys.argv[sys.argv.index("--font") + 1]
        if "--style" in sys.argv:
            style = sys.argv[sys.argv.index("--style") + 1]

        comp_script = os.path.join(SCRIPTS_DIR, "compositor.py")
        cmd = [
            sys.executable, comp_script,
            "--edl", edl_path,
            "--audio", mix_path,
            "--out", out_mp4,
            "--font", font,
            "--style", style
        ]
        if draft:
            cmd.append("--draft")

        print(f"\n=== Rendering 1080p Master for '{slug}' ===")
        print(f"Font: {font} | Caption Style: {style}\n")
        subprocess.run(cmd, cwd=project_dir)
        try:
            subprocess.run(["cmd", "/c", "start", "", out_mp4])
        except Exception:
            pass

    elif action == "short":
        short_script = os.path.join(SCRIPTS_DIR, "shorts_builder.py")
        cmd = [sys.executable, short_script, slug] + sys.argv[3:]
        subprocess.run(cmd)

    else:
        print(f"Unknown action: {action}")
        print_menu()


if __name__ == "__main__":
    main()
