"""Master End-to-End Edit Layer Pipeline Runner.
CLI: run_all.py --project <dir> [--seed N] [--motion on|off] [--broll on|off] [--approve-broll] [--draft]
Supports resumable stages (.state/<stage>.json), atomic writes, similarity checks, and deterministic seed-driven execution.
All flags default to legacy behavior (motion off, broll off).
"""
import argparse, hashlib, json, math, os, sys, tempfile, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_manager import StateManager
from edl_planner import build_edl
from broll_planner import plan_broll
from compositor import render_edl, find_ffmpeg
from check_similarity import build_effects_log, check_project_similarity

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

def generate_style_profile(project_dir, seed_val=42):
    """Emits deterministic style_profile.json based on seed and project identity."""
    proj_slug = os.path.basename(os.path.abspath(project_dir))
    seed_key = f"{proj_slug}_{seed_val}"
    seed_int = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(np.random.PCG64(seed_int))

    profile = {
        "project": proj_slug,
        "seed": seed_val,
        "effect_weights": {
            "static_ratio": round(float(rng.uniform(0.60, 0.85)), 3),
            "ken_burns_ratio": round(float(rng.uniform(0.15, 0.40)), 3),
            "punch_in_density_factor": 1.0,
            "camera_shake_density_factor": 1.0
        },
        "speed_ranges": {
            "ken_burns_zoom_max": 1.03,
            "punch_in_zoom_min": 1.04,
            "punch_in_zoom_max": 1.07,
            "shake_amplitude_max_pct": 0.004
        },
        "easing_set": ["easeInOutCubic", "easeOutQuad", "easeOutBack"],
        "transition_set": ["cut", "cutaway"],
        "punch_in_density": {
            "min_gap_sec": 6.0,
            "max_gap_sec": 10.0,
            "avg_interval_sec": 8.0,
            "min_score": 0.60
        },
        "broll_density": {
            "min_scene_duration_sec": 4.0,
            "min_cutaway_dur_sec": 1.5,
            "max_cutaway_dur_sec": 3.0,
            "exclusion_margin_sec": 0.5
        },
        "sticker_safe_zones": {
            "margin_x_pct": 0.15,
            "margin_y_pct": 0.15,
            "lead_time_ms": 50
        }
    }

    out_file = os.path.join(project_dir, "style_profile.json")
    tmp_fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix="style_", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    os.replace(tmp_path, out_file)
    return profile

def run_pipeline(project_dir, seed=42, motion=False, broll=False, parallax=False, approve_broll=False, draft=False, out_name=None, force=False):
    project_dir = os.path.abspath(project_dir)
    state = StateManager(project_dir)
    proj_slug = os.path.basename(project_dir)
    print(f"=== Running Edit Pipeline for '{proj_slug}' ===")
    print(f"Configuration: seed={seed}, motion={'on' if motion else 'off'}, parallax={'on' if parallax else 'off'}, broll={'on' if broll else 'off'}, draft={draft}, approve_broll={approve_broll}")

    # Code files tracked for versioning
    code_files = [
        os.path.join(SCRIPTS_DIR, "state_manager.py"),
        os.path.join(SCRIPTS_DIR, "edl_planner.py"),
        os.path.join(SCRIPTS_DIR, "broll_planner.py"),
        os.path.join(SCRIPTS_DIR, "compositor.py"),
        os.path.join(SCRIPTS_DIR, "check_similarity.py"),
        os.path.join(SCRIPTS_DIR, "run_all.py")
    ]

    # --- Stage 1: Style Profile ---
    stage1_inputs = [os.path.join(project_dir, "STYLE.txt")] if os.path.exists(os.path.join(project_dir, "STYLE.txt")) else []
    stage1_params = {"seed": seed, "project": proj_slug}
    h_style = state.compute_hash(stage1_inputs, stage1_params, [os.path.join(SCRIPTS_DIR, "run_all.py")])
    if not force and state.is_current("style_profile", h_style):
        print("[RESUME] Stage 1 (style_profile) is up to date. Skipping.")
        style_profile = json.load(open(os.path.join(project_dir, "style_profile.json"), "r", encoding="utf-8"))
    else:
        print("[STAGE 1] Generating style_profile.json...")
        style_profile = generate_style_profile(project_dir, seed_val=seed)
        state.save_state("style_profile", h_style, {"seed": seed})

    # --- Stage 2: EDL Planner ---
    edl_out = "edl_parallax.json" if parallax else ("edl_motion.json" if motion else "edl.json")
    stage2_inputs = [
        os.path.join(project_dir, "SCENES.tsv"),
        os.path.join(project_dir, "WORDS.tsv"),
        os.path.join(project_dir, "style_profile.json")
    ]
    if os.path.exists(os.path.join(project_dir, "mix.wav")):
        stage2_inputs.append(os.path.join(project_dir, "mix.wav"))
    stage2_params = {"seed": seed, "motion": motion, "parallax": parallax}
    h_edl = state.compute_hash(stage2_inputs, stage2_params, [os.path.join(SCRIPTS_DIR, "edl_planner.py")])

    if not force and state.is_current("edl", h_edl) and os.path.exists(os.path.join(project_dir, edl_out)):
        print(f"[RESUME] Stage 2 (EDL planner: {edl_out}) is up to date. Skipping.")
        edl = json.load(open(os.path.join(project_dir, edl_out), "r", encoding="utf-8"))
    else:
        print(f"[STAGE 2] Building EDL ({edl_out}) with motion={'on' if motion else 'off'}, parallax={'on' if parallax else 'off'}...")
        edl = build_edl(project_dir, seed_val=seed, motion=motion, parallax=parallax, out_path=edl_out)
        state.save_state("edl", h_edl, {"motion": motion, "parallax": parallax, "seed": seed})

    # --- Stage 3: B-Roll Planner ---
    broll_entries = []
    if broll:
        stage3_inputs = [
            os.path.join(project_dir, edl_out),
            os.path.join(project_dir, "WORDS.tsv"),
            os.path.join(project_dir, "SHOTS.tsv"),
            os.path.join(project_dir, "ELEMENTS.tsv")
        ]
        stage3_params = {"seed": seed, "approve_broll": approve_broll}
        h_broll = state.compute_hash(stage3_inputs, stage3_params, [os.path.join(SCRIPTS_DIR, "broll_planner.py")])

        if not force and state.is_current("broll", h_broll) and os.path.exists(os.path.join(project_dir, "broll.json")):
            print("[RESUME] Stage 3 (broll planner: broll.json) is up to date. Skipping.")
            broll_entries = json.load(open(os.path.join(project_dir, "broll.json"), "r", encoding="utf-8"))
        else:
            print("[STAGE 3] Planning B-roll cutaways...")
            broll_entries = plan_broll(project_dir, edl, seed_val=seed, out_path="broll.json")
            if approve_broll:
                print("  [APPROVAL GATE] --approve-broll is ON. Pending prompts marked approved for rendering.")
            else:
                pending_new = [b for b in broll_entries if b["source"] == "new"]
                if pending_new:
                    print(f"  [APPROVAL GATE] {len(pending_new)} new Flow prompt(s) waiting for --approve-broll.")
            state.save_state("broll", h_broll, {"seed": seed, "approve_broll": approve_broll})
    else:
        print("[STAGE 3] B-roll is OFF.")

    # --- Stage 4: Effects Log & Cross-Project Similarity ---
    stage4_inputs = [os.path.join(project_dir, edl_out)]
    if broll and os.path.exists(os.path.join(project_dir, "broll.json")):
        stage4_inputs.append(os.path.join(project_dir, "broll.json"))
    stage4_params = {"motion": motion, "broll": broll}
    h_effects = state.compute_hash(stage4_inputs, stage4_params, [os.path.join(SCRIPTS_DIR, "check_similarity.py")])

    if not force and state.is_current("effects_log", h_effects) and os.path.exists(os.path.join(project_dir, "effects_log.json")):
        print("[RESUME] Stage 4 (effects_log & similarity check) is up to date. Skipping.")
        effects_log = json.load(open(os.path.join(project_dir, "effects_log.json"), "r", encoding="utf-8"))
    else:
        print("[STAGE 4] Building effects_log.json and verifying template novelty...")
        effects_log = build_effects_log(project_dir, edl, broll_entries if broll else None)
        # Check similarity against sibling projects
        parent_dir = os.path.dirname(project_dir)
        sim_results = check_project_similarity(effects_log, search_dir=parent_dir, threshold=0.70)
        for comp in sim_results:
            if comp["warning"]:
                print(f"  [WARNING] High similarity to '{comp['other_project']}': Jaccard={comp['similarity']:.3f} > 0.70")
            else:
                print(f"  [SIMILARITY] vs '{comp['other_project']}': Jaccard={comp['similarity']:.3f} (clean)")
        state.save_state("effects_log", h_effects, {"total_effects": effects_log["total_effects"]})

    # --- Stage 5: Compositor & Render ---
    if not out_name:
        if motion and broll:
            out_name = f"{proj_slug}_motion_broll.mp4"
        elif motion:
            out_name = f"{proj_slug}_motion.mp4"
        else:
            out_name = f"{proj_slug}_baseline.mp4"

    out_mp4 = os.path.join(project_dir, out_name)
    audio_path = os.path.join(project_dir, "mix.wav")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio mix file {audio_path} not found.")

    stage5_inputs = stage4_inputs + [audio_path]
    stage5_params = {"motion": motion, "broll": broll, "draft": draft, "out_name": out_name}
    h_render = state.compute_hash(stage5_inputs, stage5_params, [os.path.join(SCRIPTS_DIR, "compositor.py")])

    if not force and state.is_current("render", h_render) and os.path.exists(out_mp4):
        print(f"[RESUME] Stage 5 (compositor: {out_name}) is up to date. Skipping.")
    else:
        print(f"[STAGE 5] Rendering {out_name} via compositor...")
        t0 = time.time()
        broll_arg = "broll.json" if broll else None
        render_edl(os.path.join(project_dir, edl_out), audio_path, out_mp4, draft=draft, broll_file=broll_arg)
        render_time = time.time() - t0
        print(f"  Finished render in {render_time:.2f} s -> {out_mp4}")
        state.save_state("render", h_render, {"render_time_s": render_time, "out_mp4": out_mp4})

    print(f"=== Pipeline Complete for '{proj_slug}' ===")
    return {
        "project": proj_slug,
        "out_mp4": out_mp4,
        "edl_file": edl_out,
        "motion": motion,
        "broll": broll,
        "effects_count": effects_log.get("total_effects", 0)
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Deterministic Edit Layer Pipeline Runner")
    ap.add_argument("--project", default=".", help="Path to project directory")
    ap.add_argument("--seed", type=int, default=42, help="Seed value (default: 42)")
    ap.add_argument("--motion", choices=["on", "off"], default="off", help="Ken Burns, punch-ins and shake (default: off)")
    ap.add_argument("--broll", choices=["on", "off"], default="off", help="B-roll cutaway layer (default: off)")
    ap.add_argument("--approve-broll", action="store_true", help="Approve generated B-roll cutaway prompts")
    ap.add_argument("--draft", action="store_true", help="Render draft resolution (960x540)")
    ap.add_argument("--force", action="store_true", help="Force re-run all stages regardless of cache")
    ap.add_argument("--out", default=None, help="Output MP4 file name")
    args = ap.parse_args()

    motion_bool = (args.motion.lower() == "on")
    broll_bool = (args.broll.lower() == "on")

    run_pipeline(
        project_dir=args.project,
        seed=args.seed,
        motion=motion_bool,
        broll=broll_bool,
        approve_broll=args.approve_broll,
        draft=args.draft,
        out_name=args.out,
        force=args.force
    )
