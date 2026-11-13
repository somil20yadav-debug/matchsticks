"""Step 3 Verification & Regression Suite (B-Roll Layer):
1. Every B-roll scene is >= 4.0 s.
2. No overlaps with sticker pops (0.5 s margin), punch-ins (0.5 s margin), or the first 3.0 s.
3. Number of cutaways is reported per video with breakdown of reuse vs new.
4. --broll off gives pixel-exact output vs current motion render (PSNR inf, SSIM 1.0).
5. A/V sync over the full length (audio and video durations within 1 frame / 0.033 s).
6. Determinism: same seed => identical broll.json, different seed => different broll.json.
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

@pytest.fixture(scope="module")
def motion_edl():
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    out_file = "edl_motion.json"
    edl = build_edl(PROJECT_DIR, seed_val=42, motion=True, out_path=out_file)
    os.chdir(orig_cwd)
    return edl

@pytest.fixture(scope="module")
def broll_plan(motion_edl):
    entries = plan_broll(PROJECT_DIR, motion_edl, seed_val=42, out_path="broll.json")
    return entries

def test_every_broll_scene_duration_ge_4s(motion_edl, broll_plan):
    """(a) Every B-roll scene is >= 4.0 s."""
    scenes_map = {s["cue"]: s for s in motion_edl["scenes"]}
    assert len(broll_plan) > 0, "No B-roll cutaways generated"

    for entry in broll_plan:
        cue = entry["scene_cue"]
        assert cue in scenes_map, f"Scene cue {cue} not found in EDL"
        sc = scenes_map[cue]
        dur = sc["duration"]
        print(f"\nB-roll entry {entry['id']} in scene {cue}: scene duration = {dur:.3f}s (>= 4.0s required)")
        assert dur >= 4.0, f"B-roll placed in scene {cue} with duration {dur:.3f}s (< 4.0s)"

def test_broll_no_overlaps_with_pops_punchins_first_3s(motion_edl, broll_plan):
    """(b) No overlaps with sticker pops (0.5s margin), punch-ins (0.5s margin), or first 3.0s."""
    scenes = motion_edl["scenes"]
    punch_ins = motion_edl.get("punch_ins", [])
    all_pops = [o["t"] for s in scenes for o in s.get("overlays", [])]
    scenes_map = {s["cue"]: s for s in scenes}

    for b in broll_plan:
        t_in = b["t_in"]
        t_out = b["t_out"]
        dur = b["duration"]
        cue = b["scene_cue"]
        sc = scenes_map[cue]

        print(f"\nChecking B-roll {b['id']} ({b['trigger_word']}): [{t_in:.3f} - {t_out:.3f}], dur={dur:.3f}s")

        # 1. First 3.0s constraint
        assert t_in >= 3.0, f"B-roll {b['id']} starts before 3.0s: {t_in:.3f}s"

        # 2. Within scene boundaries with at least 0.5s after scene start and ending on or before cut
        assert t_in >= sc["t0"] + 0.499, f"B-roll {b['id']} starts too close to scene start: {t_in:.3f} vs {sc['t0']:.3f}"
        assert t_out <= sc["t1"] + 0.001, f"B-roll {b['id']} extends past scene end: {t_out:.3f} vs {sc['t1']:.3f}"

        # 3. Duration in [1.5, 3.0]s
        assert 1.5 <= dur <= 3.001, f"B-roll {b['id']} duration {dur:.3f}s outside [1.5, 3.0]s"

        # 4. No overlap with pops (0.5s margin)
        for pop in all_pops:
            in_margin = (t_in - 0.499) <= pop <= (t_out + 0.499)
            assert not in_margin, (
                f"B-roll {b['id']} [{t_in:.3f}, {t_out:.3f}] overlaps sticker pop at {pop:.3f}s "
                f"(margin: {min(abs(t_in - pop), abs(t_out - pop)):.3f}s < 0.5s)"
            )

        # 5. No overlap with punch-ins (0.5s margin)
        for p in punch_ins:
            p_in, p_out = p["t_in"], p["t_out"]
            overlap = max(t_in - 0.499, p_in - 0.499) < min(t_out + 0.499, p_out + 0.499)
            assert not overlap, (
                f"B-roll {b['id']} [{t_in:.3f}, {t_out:.3f}] overlaps punch-in {p['word']} "
                f"[{p_in:.3f}, {p_out:.3f}] with 0.5s margin"
            )

def test_broll_cutaways_reported_per_video(motion_edl, broll_plan):
    """(c) The number of cutaways is reported per video with breakdown."""
    total_cutaways = len(broll_plan)
    reuse_count = sum(1 for b in broll_plan if b["source"] == "reuse")
    new_count = sum(1 for b in broll_plan if b["source"] == "new")

    print("\n" + "="*80)
    print(f"B-ROLL CUTAWAY REPORT: ocean-crossing (Total: {total_cutaways})")
    print(f"  - Reused local assets: {reuse_count}")
    print(f"  - New Flow prompts (pending approval): {new_count}")
    print("="*80)
    for b in broll_plan:
        src = f"REUSE ({b['asset']})" if b['source'] == 'reuse' else f"NEW PROMPT: '{b['prompt'][:45]}...'"
        print(f"  [{b['id']}] Scene {b['scene_cue']:>5} | Word: '{b['trigger_word']}' | {b['t_in']:.2f}s - {b['t_out']:.2f}s ({b['duration']:.2f}s) | {src}")
    print("="*80)

    assert total_cutaways > 0
    assert reuse_count >= 1

def test_broll_off_pixel_exact_baseline(motion_edl):
    """(d) --broll off gives pixel-exact output vs current render (PSNR inf, SSIM 1.0)."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)
    
    baseline_mp4 = os.path.join(PROJECT_DIR, "ocean-crossing_motion.mp4")
    assert os.path.exists(baseline_mp4), "ocean-crossing_motion.mp4 must exist as baseline"

    # Render a 20s test clip with broll_file=None
    test_edl_path = "edl_motion.json"
    audio_path = "mix.wav"
    broll_off_mp4 = "test_broll_off.mp4"

    # Temporarily render 20s to compare
    orig_total = motion_edl["total_duration"]
    motion_edl["total_duration"] = 20.0
    with open("test_edl_20s.json", "w", encoding="utf-8") as f:
        json.dump(motion_edl, f)
    motion_edl["total_duration"] = orig_total

    render_edl("test_edl_20s.json", audio_path, broll_off_mp4, broll_file=None)
    os.chdir(orig_cwd)

    # Sample frames from baseline and test_broll_off
    cap_base = cv2.VideoCapture(baseline_mp4)
    cap_test = cv2.VideoCapture(os.path.join(PROJECT_DIR, broll_off_mp4))

    for frame_idx in [30, 90, 150, 300, 450, 550]:
        cap_base.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        cap_test.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret1, f1 = cap_base.read()
        ret2, f2 = cap_test.read()
        assert ret1 and ret2, f"Failed to read frame {frame_idx}"
        diff = np.max(np.abs(f1.astype(np.int32) - f2.astype(np.int32)))
        p_val = psnr(f1, f2)
        s_val = ssim(f1, f2, channel_axis=2)
        print(f"Frame {frame_idx} --broll off comparison: max pixel diff = {diff}, PSNR = {p_val:.1f} dB, SSIM = {s_val:.4f}")
        assert diff == 0, f"Frame {frame_idx} differs when --broll off! max diff = {diff}"
        assert math.isinf(p_val) or p_val > 90, f"Frame {frame_idx} PSNR not inf: {p_val}"
        assert s_val == 1.0, f"Frame {frame_idx} SSIM not 1.0: {s_val}"

    cap_base.release()
    cap_test.release()
    # Cleanup
    for tmp in ["test_broll_off.mp4", "test_edl_20s.json"]:
        p = os.path.join(PROJECT_DIR, tmp)
        if os.path.exists(p):
            os.remove(p)

def test_broll_full_av_sync_and_render(motion_edl, broll_plan):
    """(e) Render full ocean-crossing with B-roll on and verify A/V sync diff <= 1 frame."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)

    out_mp4 = "ocean-crossing_broll.mp4"
    audio_path = "mix.wav"
    t_start = time.time()
    render_edl("edl_motion.json", audio_path, out_mp4, broll_file="broll.json")
    dur_render = time.time() - t_start
    os.chdir(orig_cwd)

    full_mp4_path = os.path.join(PROJECT_DIR, out_mp4)
    assert os.path.exists(full_mp4_path), f"{out_mp4} was not generated"

    v_dur, a_dur = get_stream_durations(full_mp4_path)
    drift = abs(v_dur - a_dur)
    file_size_mb = os.path.getsize(full_mp4_path) / (1024 * 1024)

    print(f"\nRendered ocean-crossing with B-roll on:")
    print(f"  Path: {full_mp4_path}")
    print(f"  Render time: {dur_render:.2f} s")
    print(f"  Size: {file_size_mb:.2f} MB")
    print(f"  Video duration: {v_dur:.6f} s")
    print(f"  Audio duration: {a_dur:.6f} s")
    print(f"  A/V sync drift: {drift * 1000:.3f} ms (max allowed = 33.3 ms / 1 frame)")

    assert drift <= 0.0333, f"A/V sync drift exceeded 1 frame: {drift:.6f} s"

    # Verify that during a reused B-roll cutaway, the frame visibly changed from the base scene
    # broll_01 is in scene 11.0: [38.799, 41.149]. Frame at t=39.5s vs t=37.5s (base scene)
    cap = cv2.VideoCapture(full_mp4_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, 37500)  # t=37.5s (before cutaway)
    r1, f_base = cap.read()
    cap.set(cv2.CAP_PROP_POS_MSEC, 39500)  # t=39.5s (during cutaway)
    r2, f_broll = cap.read()
    cap.release()

    assert r1 and r2, "Failed to read B-roll verification frames"
    diff = np.mean(np.abs(f_base.astype(np.float32) - f_broll.astype(np.float32)))
    print(f"Mean pixel diff between base scene and B-roll cutaway: {diff:.2f}")
    assert diff > 10.0, f"B-roll cutaway frame does not differ from base scene: mean diff = {diff}"

def test_broll_seed_determinism(motion_edl):
    """(f) Determinism: same seed => same broll.json, different seed => different broll.json."""
    orig_cwd = os.getcwd()
    os.chdir(PROJECT_DIR)

    plan1 = plan_broll(PROJECT_DIR, motion_edl, seed_val=42, out_path="broll_seed42_a.json")
    plan2 = plan_broll(PROJECT_DIR, motion_edl, seed_val=42, out_path="broll_seed42_b.json")
    plan_other = plan_broll(PROJECT_DIR, motion_edl, seed_val=999, out_path="broll_seed999.json")

    with open("broll_seed42_a.json", "rb") as f:
        h1 = hashlib.sha256(f.read()).hexdigest()
    with open("broll_seed42_b.json", "rb") as f:
        h2 = hashlib.sha256(f.read()).hexdigest()
    with open("broll_seed999.json", "rb") as f:
        h_other = hashlib.sha256(f.read()).hexdigest()

    # Clean up temp test files
    for tmp in ["broll_seed42_a.json", "broll_seed42_b.json", "broll_seed999.json"]:
        if os.path.exists(tmp):
            os.remove(tmp)
    os.chdir(orig_cwd)

    print(f"\nB-roll determinism check:")
    print(f"  Seed 42 (run 1) SHA256: {h1}")
    print(f"  Seed 42 (run 2) SHA256: {h2}")
    print(f"  Seed 999        SHA256: {h_other}")

    assert h1 == h2, "Same seed produced different broll.json!"
    assert h1 != h_other, "Different seed produced identical broll.json!"
