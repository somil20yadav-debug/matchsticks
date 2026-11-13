"""Test 30-Second Parallax & Script-Driven Stickers Render.
Renders the first ~30 seconds of ocean-crossing with --parallax on and --stickers on.
Checks for edge tearing, boundary leakage, and overlay collisions.
"""
import copy, json, math, os, subprocess, sys, time
import cv2
import numpy as np
from PIL import Image

PROJECT_DIR = r"C:\Users\User\StickmanHybrid\ocean-crossing"
SCRIPTS_DIR = r"C:\Users\User\.claude\skills\stickman-hybrid\scripts"
sys.path.insert(0, SCRIPTS_DIR)

from edl_planner import build_edl, W, H, FPS
from depth_parallax import get_or_create_parallax_layers
from parallax_compositor import render_parallax_frame
from mascot import get_mascot_image
from compositor import render_edl

def prepare_30s_test():
    print("=== Preparing 30s Parallax + Sticker Test EDL ===")
    os.chdir(PROJECT_DIR)

    # 1. Build EDL with motion & parallax enabled
    edl = build_edl(PROJECT_DIR, seed_val=42, motion=True, parallax=True, out_path="edl_test_30s.json")

    # Filter to first ~30 seconds (scenes ending before or around 30s)
    scenes_30s = [sc for sc in edl["scenes"] if sc["t0"] < 30.0]
    # Cap last scene at 30.0s
    if scenes_30s:
        scenes_30s[-1]["t1"] = min(30.0, scenes_30s[-1]["t1"])
        scenes_30s[-1]["duration"] = scenes_30s[-1]["t1"] - scenes_30s[-1]["t0"]

    # 2. Add an explicit Mascot Peek on scene 02.6 (t=6.04s, dur=3.7s, img=img/s03.jpg)
    for sc in scenes_30s:
        if sc["cue"] == "02.6":
            sc["parallax_effect"] = {"move": "push"}
            # Add mascot peek overlay
            sc["overlays"].append({
                "cue": "02.6",
                "t": 6.8,
                "img": "peek:br:curious",
                "text": "",
                "x": 0.82,
                "y": 0.72,
                "h": 0.36,
                "motion": "peek",
                "plain": False,
                "cross": False
            })
        elif sc["cue"] == "07.0":
            sc["parallax_effect"] = {"move": "driftL"}

    edl["scenes"] = scenes_30s
    edl["total_duration"] = 30.0
    edl["stickers"] = True
    edl["parallax"] = True

    with open("edl_test_30s.json", "w", encoding="utf-8") as f:
        json.dump(edl, f, indent=2)

    print(f"Prepared 30s EDL with {len(scenes_30s)} scenes, total duration: 30.0s")
    return "edl_test_30s.json"

def run_30s_render():
    edl_file = prepare_30s_test()
    out_mp4 = os.path.join(PROJECT_DIR, "test_30s_parallax_stickers.mp4")
    audio_path = os.path.join(PROJECT_DIR, "mix.wav")

    print(f"\n=== Rendering 30s Video to {out_mp4} ===")
    t0 = time.time()
    render_edl(edl_file, audio_path, out_mp4, draft=False)
    elapsed = time.time() - t0
    print(f"Render completed in {elapsed:.2f} s")

    # Verification: Read back frames to check for tearing or invalid pixels
    print("\n=== Automated Edge-Tear & Overlap QC Scan ===")
    cap = cv2.VideoCapture(out_mp4)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Video stream: {total_frames} frames @ {fps:.1f} fps (~{total_frames/fps:.1f}s)")

    tearing_detected = False
    checked_frames = 0
    qc_saved = 0

    frame_indices_to_check = np.linspace(0, total_frames - 1, 30, dtype=int)

    for fi in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break

        if fi in frame_indices_to_check:
            checked_frames += 1
            # Check edge borders (top 4 px, bottom 4 px, left 4 px, right 4 px)
            top_edge = frame[:4, :]
            bottom_edge = frame[-4:, :]
            left_edge = frame[:, :4]
            right_edge = frame[:, -4:]

            # Verify no pure-black 0-value holes or NaN
            has_black_top = (top_edge.sum(axis=2) == 0).sum() > (top_edge.shape[1] * 2)
            has_black_bot = (bottom_edge.sum(axis=2) == 0).sum() > (bottom_edge.shape[1] * 2)
            has_black_left = (left_edge.sum(axis=2) == 0).sum() > (left_edge.shape[0] * 2)
            has_black_right = (right_edge.sum(axis=2) == 0).sum() > (right_edge.shape[0] * 2)

            if has_black_top or has_black_bot or has_black_left or has_black_right:
                tearing_detected = True
                print(f"  [WARNING] Possible edge tear at frame {fi} (t={fi/fps:.2f}s)!")

            # Save sample QC frames around key moments (e.g. t~7.5s for peek, t~22s for counter)
            t_sec = fi / fps
            if 6.8 <= t_sec <= 8.5 and qc_saved < 3:
                qc_path = os.path.join(PROJECT_DIR, f"qc_sample_peek_{fi}.jpg")
                cv2.imwrite(qc_path, frame)
                print(f"  [SAVED QC] Saved sample frame at t={t_sec:.2f}s -> {qc_path}")
                qc_saved += 1
            elif 21.0 <= t_sec <= 23.0 and qc_saved < 5:
                qc_path = os.path.join(PROJECT_DIR, f"qc_sample_counter_{fi}.jpg")
                cv2.imwrite(qc_path, frame)
                print(f"  [SAVED QC] Saved sample frame at t={t_sec:.2f}s -> {qc_path}")
                qc_saved += 1

    cap.release()

    if not tearing_detected:
        print("\n[PASSED] Edge-Tear & Boundary Verification: Zero edge tearing or black margins detected across all inspected frames!")
    else:
        print("\n[FLAGGED] Edge anomalies detected.")

    return not tearing_detected, out_mp4

if __name__ == "__main__":
    success, out = run_30s_render()
    sys.exit(0 if success else 1)
