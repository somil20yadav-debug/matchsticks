"""Step 4 & Phase 4 Full Verification Suite:
1. Determinism: Same seed => identical EDL hash; different seed => EDL distance above threshold.
2. Punch-in spacing & quality: Gaps >= 6.0s (jittered 6-10s window), no identical consecutive effects.
3. Flag-off backward compatibility: All flags off => frames match legacy baseline (PSNR inf, SSIM 1.0).
4. ffprobe A/V sync: Audio and video stream durations match within 1 frame (<= 33 ms).
5. check_similarity.py: Jaccard similarity correctly flags near-duplicate sequences above 0.70 threshold.
"""
import hashlib, json, math, os, subprocess, sys, time
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

from edl_planner import build_edl, W, H, FPS
from broll_planner import plan_broll
from compositor import render_edl
from check_similarity import (
    extract_effects_sequence, build_effects_log, compute_jaccard_similarity, check_project_similarity
)
from run_all import run_pipeline, generate_style_profile

def get_stream_durations(mp4_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
        "-of", "json", mp4_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    info = json.loads(res.stdout)
    v_dur = next(float(s["duration"]) for s in info["streams"] if s["codec_type"] == "video")
    a_dur = next(float(s["duration"]) for s in info["streams"] if s["codec_type"] == "audio")
    return v_dur, a_dur

def test_same_seed_identical_edl_different_seed_different():
    """1. Same seed => identical EDL hash; different seed => EDL distance above threshold."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)

    edl1 = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path="test_edl_42_a.json")
    edl2 = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path="test_edl_42_b.json")
    edl_diff = build_edl(PROJECT_DIR, seed_val=999, motion=True, out_path="test_edl_999.json")

    with open("test_edl_42_a.json", "rb") as f:
        h1 = hashlib.sha256(f.read()).hexdigest()
    with open("test_edl_42_b.json", "rb") as f:
        h2 = hashlib.sha256(f.read()).hexdigest()
    with open("test_edl_999.json", "rb") as f:
        h_diff = hashlib.sha256(f.read()).hexdigest()

    # Clean up test files
    for f in ["test_edl_42_a.json", "test_edl_42_b.json", "test_edl_999.json"]:
        if os.path.exists(f):
            os.remove(f)
    os.chdir(orig_cwd)

    print(f"\nEDL Determinism Verification:")
    print(f"  Seed 42 Run 1 SHA256: {h1}")
    print(f"  Seed 42 Run 2 SHA256: {h2}")
    print(f"  Seed 999      SHA256: {h_diff}")

    assert h1 == h2, "Same seed produced non-identical EDL hash!"
    assert h1 != h_diff, "Different seed produced identical EDL hash!"

    # Calculate distance between effect sequences of edl1 and edl_diff
    seq1 = extract_effects_sequence(edl1)
    seq_diff = extract_effects_sequence(edl_diff)
    sim = compute_jaccard_similarity(seq1, seq_diff)
    dist = 1.0 - sim
    print(f"  EDL sequence Jaccard distance between seed 42 and 999: {dist:.3f}")
    assert dist > 0.15, f"EDL distance between different seeds was too small: {dist:.3f}"

def test_punch_in_gaps_and_no_identical_consecutive_effects():
    """2. Punch-in gaps in [6, 10]s (jittered); no identical consecutive effects."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    edl = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path="edl_motion.json")
    broll = json.load(open("broll.json", "r", encoding="utf-8")) if os.path.exists("broll.json") else None
    os.chdir(orig_cwd)

    punch_ins = edl["punch_ins"]
    print(f"\nTotal planned punch-ins: {len(punch_ins)}")
    for i in range(len(punch_ins) - 1):
        gap = punch_ins[i+1]["t_in"] - punch_ins[i]["t_out"]
        word1, word2 = punch_ins[i]["word"], punch_ins[i+1]["word"]
        print(f"  Gap between '{word1}' and '{word2}': {gap:.3f} s")
        # Enforce minimum gap of 6.0s
        assert gap >= 5.99, f"Punch-in gap {gap:.3f}s between '{word1}' and '{word2}' is less than 6.0s!"

    # Check for no identical consecutive effects in the sequence
    seq = extract_effects_sequence(edl, broll)
    print(f"\nTotal effect events: {len(seq)}")
    consecutive_repeats = []
    for i in range(len(seq) - 1):
        e1, e2 = seq[i], seq[i+1]
        # Allow static scenes in a row (baseline), but no consecutive identical dynamic effects (punch-in, shake, ken burns)
        if e1 == e2 and not e1.startswith("scene:static") and not e1.startswith("pop:"):
            consecutive_repeats.append((i, e1))

    print(f"  Consecutive identical dynamic effects: {len(consecutive_repeats)}")
    assert len(consecutive_repeats) == 0, f"Found identical consecutive effects: {consecutive_repeats}"

def test_all_flags_off_matches_baseline_psnr_ssim():
    """3. All flags off => frames match the baseline (PSNR inf, SSIM 1.0)."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)

    try:
        from render import set_look, picture, card, label, bars, CHART, W, H
        set_look("painted")
        from compositor import render_base_scene

        edl = build_edl(PROJECT_DIR, seed_val=42, motion=False, out_path="edl.json")
        scenes = edl["scenes"]

        sample_indices = [0, 5, 20, 45, len(scenes) - 1]
        for idx in sample_indices:
            sc = scenes[idx]
            new_fr = render_base_scene(sc, PROJECT_DIR)
            new_rgb = np.array(new_fr.convert("RGB"), dtype=np.uint8)

            img, text, pos, extra = [sc["img"], sc["text"], sc["pos"], sc["extra"]]
            leg_pic = card() if img == "card" else picture(img)
            blocked = []
            if extra.startswith("bars:"):
                bars(leg_pic, extra[5:])
                blocked.append(CHART)
            for o in sc["overlays"]:
                hh = o["h"] * H
                ww = hh * 1.2
                blocked.append((o["x"] * W - ww / 2, o["y"] * H - hh / 2, o["x"] * W + ww / 2, o["y"] * H + hh / 2))
            if text:
                label(leg_pic, text, "big" if img == "card" else (pos if pos.endswith("!") else "auto"), blocked)
            leg_rgb = np.array(leg_pic.convert("RGB"), dtype=np.uint8)

            diff = np.max(np.abs(leg_rgb.astype(np.int32) - new_rgb.astype(np.int32)))
            score_psnr = psnr(leg_rgb, new_rgb)
            score_ssim = ssim(leg_rgb, new_rgb, channel_axis=2)

            print(f"Scene {sc['cue']} Flag-Off vs Legacy: max diff = {diff}, PSNR = {score_psnr} dB, SSIM = {score_ssim:.4f}")
            assert diff == 0, f"Pixel difference {diff} at scene {sc['cue']} with flags off!"
            assert score_psnr == float("inf"), f"Scene {sc['cue']} PSNR not inf: {score_psnr}"
            assert score_ssim == 1.0, f"Scene {sc['cue']} SSIM not 1.0: {score_ssim}"
    finally:
        os.chdir(orig_cwd)

def test_ffprobe_av_duration_within_one_frame():
    """4. ffprobe: A/V duration within 1 frame (<= 33 ms)."""
    test_videos = [
        os.path.join(PROJECT_DIR, "ocean-crossing_motion.mp4"),
        os.path.join(PROJECT_DIR, "ocean-crossing_broll.mp4")
    ]
    for mp4 in test_videos:
        if not os.path.exists(mp4):
            continue
        v_dur, a_dur = get_stream_durations(mp4)
        drift = abs(v_dur - a_dur)
        print(f"\nChecking A/V Sync for {os.path.basename(mp4)}:")
        print(f"  Video: {v_dur:.6f} s | Audio: {a_dur:.6f} s | Drift: {drift * 1000:.3f} ms")
        assert drift <= 0.0333, f"A/V drift exceeded 1 frame (33.3 ms): {drift * 1000:.3f} ms"

def test_check_similarity_flags_near_duplicates():
    """5. check_similarity.py flags near-duplicate effect sequences above 0.70."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    edl = json.load(open("edl_motion.json", "r", encoding="utf-8"))
    broll = json.load(open("broll.json", "r", encoding="utf-8")) if os.path.exists("broll.json") else None
    log_data = build_effects_log(PROJECT_DIR, edl, broll, out_path="effects_log.json")
    base_seq = log_data["effects_sequence"]

    # 1. Near-duplicate sequence: mutate only 2 tokens out of ~100
    near_dup = list(base_seq)
    near_dup[5] = "scene:ken_burns:zoom_in"
    near_dup[20] = "pop:custom_pop.png"
    sim_high = compute_jaccard_similarity(base_seq, near_dup)
    print(f"\nNear-duplicate test sequence Jaccard similarity: {sim_high:.4f}")
    assert sim_high > 0.70, f"Expected high similarity > 0.70, got {sim_high:.4f}"

    # 2. Diverse/distinct sequence (e.g. inverted structure or different project)
    diverse_seq = ["scene:static", "pop:unrelated.png", "punch_in:contrast", "scene:ken_burns:zoom_out"] * 10
    sim_low = compute_jaccard_similarity(base_seq, diverse_seq)
    print(f"Diverse test sequence Jaccard similarity: {sim_low:.4f}")
    assert sim_low < 0.70, f"Expected low similarity < 0.70, got {sim_low:.4f}"

    # 3. Test check_project_similarity warning flag
    # Write a dummy sibling project with near_dup log
    dummy_dir = os.path.join(os.path.dirname(PROJECT_DIR), "ocean-crossing-clone")
    os.makedirs(dummy_dir, exist_ok=True)
    dummy_log_file = os.path.join(dummy_dir, "effects_log.json")
    with open(dummy_log_file, "w", encoding="utf-8") as f:
        json.dump({
            "project": "ocean-crossing-clone",
            "effects_sequence": near_dup
        }, f)

    comparisons = check_project_similarity(log_data, search_dir=os.path.dirname(PROJECT_DIR), threshold=0.70)
    print("Cross-project comparison results:")
    for comp in comparisons:
        print(f"  vs {comp['other_project']}: sim={comp['similarity']}, warning={comp['warning']}")

    # Clean up dummy project
    if os.path.exists(dummy_log_file):
        os.remove(dummy_log_file)
    if os.path.exists(dummy_dir):
        os.rmdir(dummy_dir)
    os.chdir(orig_cwd)

    clone_match = next((c for c in comparisons if c["other_project"] == "ocean-crossing-clone"), None)
    assert clone_match is not None, "Failed to find clone project comparison"
    assert clone_match["warning"] is True, "Failed to flag near-duplicate clone project!"
    assert clone_match["similarity"] > 0.70, f"Clone similarity {clone_match['similarity']} <= 0.70"

def test_run_all_pipeline_resumable_execution():
    """6. run_all.py: Resumable stages skip when inputs+params+code match (.state/<stage>.json)."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)

    test_out = "test_resumable_clip.mp4"
    audio_path = "mix.wav"

    # Temporarily set total_duration to 5.0s for fast verification
    edl_motion_path = "edl_motion.json"
    with open(edl_motion_path, "r", encoding="utf-8") as f:
        edl = json.load(f)
    orig_total = edl["total_duration"]

    try:
        edl["total_duration"] = 5.0
        with open("edl_test_5s.json", "w", encoding="utf-8") as f:
            json.dump(edl, f)

        # Run 1: Execution
        t0 = time.time()
        res1 = run_pipeline(
            PROJECT_DIR, seed=42, motion=True, broll=True, draft=True, out_name=test_out, force=True
        )
        t_run1 = time.time() - t0
        print(f"\nRun 1 (force=True) time: {t_run1:.2f} s")
        assert os.path.exists(res1["out_mp4"]), "Pipeline failed to produce output MP4"

        # Run 2: Cached execution (all stages should skip)
        t0 = time.time()
        res2 = run_pipeline(
            PROJECT_DIR, seed=42, motion=True, broll=True, draft=True, out_name=test_out, force=False
        )
        t_run2 = time.time() - t0
        print(f"Run 2 (cached) time: {t_run2:.2f} s (expected < 1.5s)")

        assert t_run2 < 2.0, f"Cached run took too long ({t_run2:.2f}s), stage skipping failed"
    finally:
        for f in [test_out, "edl_test_5s.json"]:
            if os.path.exists(f):
                os.remove(f)
        os.chdir(orig_cwd)
