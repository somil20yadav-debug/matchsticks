import json, os, numpy as np

project_dir = r"C:\Users\User\StickmanHybrid\ocean-crossing"
edl_path = os.path.join(project_dir, "edl_motion.json")
with open(edl_path, "r", encoding="utf-8") as f:
    edl = json.load(f)

scenes = edl["scenes"]
W, H = 1920, 1080
FPS = 30

punch_in_times = [(p["t_in"], p["t_out"]) for p in edl.get("punch_ins", [])]

def has_punch_in(t0, t1):
    return any(max(t0, p0) < min(t1, p1) for p0, p1 in punch_in_times)

hdr = "{:<7} | {:<16} | {:<6} | {:<6} | {:<6} | {:<9} | {:<14} | {:<8} | {}".format(
    "Scene", "Type", "Dur", "MinZ", "MaxZ", "MaxPanPx", "MaxDispPx/Fr", "PunchIn", "Flag"
)
print("Total scenes:", len(scenes))
print(hdr)
print("-" * len(hdr))

flagged = 0
for sc in scenes:
    dur = sc["duration"]
    eff = sc["base_effect"]
    t_type = eff.get("type", "static")
    z0 = float(eff.get("zoom_start", 1.0))
    z1 = float(eff.get("zoom_end", 1.0))
    px = float(eff.get("pan_x", 0.0)) * W
    py = float(eff.get("pan_y", 0.0)) * H
    max_pan = float(np.hypot(px, py))
    
    n_frames = max(2, int(dur * FPS))
    ts = np.linspace(0, 1, n_frames)
    
    easing = eff.get("easing", "linear")
    if easing == "easeInOutCubic":
        p = np.where(ts < 0.5, 4 * ts**3, 1 - (-2 * ts + 2)**3 / 2)
    elif easing == "easeInOutSine":
        p = -(np.cos(np.pi * ts) - 1) / 2
    else:
        p = ts
        
    shifts_x = px * p
    shifts_y = py * p
    deltas = np.hypot(np.diff(shifts_x), np.diff(shifts_y))
    max_disp = float(np.max(deltas)) if len(deltas) else 0.0
    
    pi_active = has_punch_in(sc["t0"], sc["t1"])
    flag = "OK"
    if (not pi_active) and max_disp > 0.3:
        flag = "HIGH DISP > 0.3 px/fr!"
        flagged += 1
    cue = sc["cue"]
    print("{:<7} | {:<16} | {:<5.2f}s | {:<6.3f} | {:<6.3f} | {:<9.2f} | {:<14.3f} | {:<8} | {}".format(
        cue, t_type, dur, min(z0, z1), max(z0, z1), max_pan, max_disp, "YES" if pi_active else "NO", flag
    ))

print("-" * len(hdr))
print(f"Flagged scenes (outside punch-in with displacement > 0.3 px/frame): {flagged} / {len(scenes)}")
