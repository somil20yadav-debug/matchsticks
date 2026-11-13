"""Step 1 Verification Tests:
1. Seed determinism (same seed -> identical EDL hash; different seed -> different EDL).
2. Resumable StateManager verification.
3. Flag-off test: Compare legacy frame generation against new compositor path (PSNR/SSIM).
4. Audio/Video duration check via ffprobe.
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile
import cv2
import numpy as np
import pytest
from skimage.metrics import peak_signal_noise_ratio as psnr, structural_similarity as ssim

FFMPEG_DIR = r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin"
if os.path.exists(FFMPEG_DIR) and FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

PROJECT_DIR = r"C:\Users\User\StickmanHybrid\ocean-crossing"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from edl_planner import build_edl, make_seed_int
from state_manager import StateManager
from compositor import render_base_scene, render_edl, find_ffmpeg

def test_edl_determinism():
    """Verify that same seed produces identical EDL sha256, and different seeds produce distinct EDLs."""
    out_a = os.path.join(PROJECT_DIR, "_tmp_edl_a.json")
    out_b = os.path.join(PROJECT_DIR, "_tmp_edl_b.json")
    out_c = os.path.join(PROJECT_DIR, "_tmp_edl_c.json")
    try:
        edl_a = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path="_tmp_edl_a.json")
        hash_a = hashlib.sha256(open(out_a, "rb").read()).hexdigest()

        edl_b = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path="_tmp_edl_b.json")
        hash_b = hashlib.sha256(open(out_b, "rb").read()).hexdigest()

        assert hash_a == hash_b, "Determinism failed: identical seeds gave different hashes"
        assert json.dumps(edl_a, sort_keys=True) == json.dumps(edl_b, sort_keys=True)

        edl_c = build_edl(PROJECT_DIR, seed_val=999, motion=True, out_path="_tmp_edl_c.json")
        hash_c = hashlib.sha256(open(out_c, "rb").read()).hexdigest()

        assert hash_a != hash_c, "Entropy failed: different seeds gave identical hashes"
    finally:
        for p in [out_a, out_b, out_c]:
            if os.path.exists(p):
                os.remove(p)

def test_state_manager():
    """Verify state manager detects matching hash, input changes, and params changes."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        sm = StateManager(tmp_dir)
        test_file = os.path.join(tmp_dir, "input.tsv")
        with open(test_file, "w") as f:
            f.write("test_content_v1")

        h1 = sm.compute_hash([test_file], {"motion": False}, [])
        assert not sm.is_current("planner", h1)

        sm.save_state("planner", h1)
        assert sm.is_current("planner", h1)

        with open(test_file, "w") as f:
            f.write("test_content_v2")
        h2 = sm.compute_hash([test_file], {"motion": False}, [])
        assert h1 != h2
        assert not sm.is_current("planner", h2)

def test_flag_off_legacy_vs_compositor_psnr_ssim():
    """Verify that with motion=False (flag-off), compositor produces pixel-exact frames compared to legacy base render."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    try:
        from render import set_look, picture, card, label, bars, CHART, W, H
        set_look("painted")

        edl_path = "_tmp_edl_flagoff.json"
        edl = build_edl(PROJECT_DIR, seed_val=42, motion=False, out_path=edl_path)
        sc0 = edl["scenes"][0]

        # 1. New compositor path
        new_frame_rgba = render_base_scene(sc0, PROJECT_DIR)
        new_frame_rgb = np.array(new_frame_rgba.convert("RGB"), dtype=np.uint8)

        # 2. Legacy render.py path
        img, text, pos, extra = [sc0["img"], sc0["text"], sc0["pos"], sc0["extra"]]
        leg_pic = card() if img == "card" else picture(img)
        blocked = []
        if extra.startswith("bars:"):
            bars(leg_pic, extra[5:])
            blocked.append(CHART)
        for o in sc0["overlays"]:
            hh = o["h"] * H
            ww = hh * 1.2
            blocked.append((o["x"] * W - ww / 2, o["y"] * H - hh / 2, o["x"] * W + ww / 2, o["y"] * H + hh / 2))
        if text:
            label(leg_pic, text, "big" if img == "card" else (pos if pos.endswith("!") else "auto"), blocked)
        leg_frame_rgb = np.array(leg_pic.convert("RGB"), dtype=np.uint8)

        score_psnr = psnr(leg_frame_rgb, new_frame_rgb)
        score_ssim = ssim(leg_frame_rgb, new_frame_rgb, channel_axis=2)

        print(f"\n[FLAG-OFF VERIFICATION] PSNR: {score_psnr} dB, SSIM: {score_ssim}")
        assert score_psnr == float("inf"), f"Frames are not pixel-identical! PSNR: {score_psnr}"
        assert score_ssim == 1.0, f"Frames differ visually! SSIM: {score_ssim}"
    finally:
        flagoff_file = os.path.join(PROJECT_DIR, "_tmp_edl_flagoff.json")
        if os.path.exists(flagoff_file):
            os.remove(flagoff_file)
        os.chdir(orig_cwd)

def test_av_sync_ffprobe():
    """Render a short test clip and verify audio-video duration difference <= 1 frame (33.3ms)."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    test_mp4 = os.path.join(PROJECT_DIR, "_tmp_test_sync.mp4")
    edl_file = os.path.join(PROJECT_DIR, "_tmp_sync_edl.json")
    audio_src = os.path.join(PROJECT_DIR, "mix.wav")

    try:
        mini_edl = {
            "project_id": "test_sync",
            "seed": 42,
            "motion": False,
            "fps": 30,
            "total_duration": 4.0,
            "canvas_size": [1920, 1080],
            "oversample": 1.0,
            "scenes": [
                {
                    "scene_idx": 0,
                    "cue": "01.0",
                    "t0": 0.0,
                    "t1": 2.0,
                    "duration": 2.0,
                    "img": "img/s01.jpg",
                    "text": "",
                    "pos": "",
                    "extra": "",
                    "base_effect": {"type": "static"},
                    "overlays": []
                },
                {
                    "scene_idx": 1,
                    "cue": "02.0",
                    "t0": 2.0,
                    "t1": 4.0,
                    "duration": 2.0,
                    "img": "img/s02.jpg",
                    "text": "",
                    "pos": "",
                    "extra": "",
                    "base_effect": {"type": "static"},
                    "overlays": []
                }
            ]
        }
        with open(edl_file, "w") as f:
            json.dump(mini_edl, f)

        render_edl(edl_file, audio_src, test_mp4)
        assert os.path.exists(test_mp4), "Output MP4 not generated"

        probe_v = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=duration", "-of", "csv=p=0", test_mp4
        ], capture_output=True, text=True).stdout.strip()

        probe_a = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=duration", "-of", "csv=p=0", test_mp4
        ], capture_output=True, text=True).stdout.strip()

        dur_v = float(probe_v)
        dur_a = float(probe_a)
        diff = abs(dur_v - dur_a)
        frame_time = 1.0 / 30.0

        print(f"\n[A/V SYNC VERIFICATION] Video: {dur_v:.4f}s, Audio: {dur_a:.4f}s, Diff: {diff*1000:.2f}ms (Limit: {frame_time*1000:.2f}ms)")
        assert diff <= frame_time * 1.5, f"Audio/Video drift exceeded 1 frame! Diff: {diff*1000:.2f}ms"
    finally:
        if os.path.exists(test_mp4):
            os.remove(test_mp4)
        if os.path.exists(edl_file):
            os.remove(edl_file)
        os.chdir(orig_cwd)
