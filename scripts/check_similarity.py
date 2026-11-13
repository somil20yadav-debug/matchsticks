"""Effects Log and Cross-Project Sequence Similarity Checker.
1. Extracts chronological sequence of edit effects from EDL + B-roll.
2. Emits effects_log.json.
3. Computes n-gram Jaccard similarity across projects.
4. Emits warning if Jaccard similarity > 0.70.
"""
import argparse, json, math, os, re, sys, tempfile

def clean_token(s):
    return re.sub(r"[^\w]", "", str(s)).strip().lower()

def extract_effects_sequence(edl, broll_entries=None):
    """Extracts chronological sequence of visual edit effects."""
    events = []

    # 1. Base scene camera effects
    for sc in edl.get("scenes", []):
        t0 = sc["t0"]
        eff = sc.get("base_effect", {})
        eff_type = eff.get("type", "static")
        if eff_type == "ken_burns":
            z0 = eff.get("zoom_start", 1.0)
            z1 = eff.get("zoom_end", 1.0)
            direction = "zoom_in" if z1 >= z0 else "zoom_out"
            events.append((t0, f"scene:ken_burns:{direction}"))
        else:
            events.append((t0, "scene:static"))

        # Overlays / sticker pops
        for o in sc.get("overlays", []):
            img_name = os.path.basename(o.get("img", "overlay"))
            events.append((o["t"], f"pop:{img_name}"))

    # 2. Punch-ins
    for p in edl.get("punch_ins", []):
        w = clean_token(p.get("word", "word"))
        events.append((p["t_in"], f"punch_in:{w}"))

    # 3. Camera shakes
    for s in edl.get("camera_shakes", []):
        events.append((s["t_in"], f"shake:{s.get('type', 'tremor')}"))

    # 4. B-roll cutaways
    if broll_entries:
        for b in broll_entries:
            w = clean_token(b.get("trigger_word", "broll"))
            src = b.get("source", "reuse")
            events.append((b["t_in"], f"broll:{src}:{w}"))

    # Sort strictly by timestamp
    events.sort(key=lambda ev: ev[0])
    return [ev[1] for ev in events]

def build_effects_log(project_dir, edl, broll_entries=None, out_path="effects_log.json"):
    """Emits effects_log.json with atomic write."""
    seq = extract_effects_sequence(edl, broll_entries)
    
    counts = {
        "static_scenes": sum(1 for e in seq if e == "scene:static"),
        "ken_burns_scenes": sum(1 for e in seq if e.startswith("scene:ken_burns")),
        "pops": sum(1 for e in seq if e.startswith("pop:")),
        "punch_ins": sum(1 for e in seq if e.startswith("punch_in:")),
        "camera_shakes": sum(1 for e in seq if e.startswith("shake:")),
        "broll_cutaways": sum(1 for e in seq if e.startswith("broll:"))
    }

    log_data = {
        "project": os.path.basename(os.path.abspath(project_dir)),
        "seed": edl.get("seed", 42),
        "motion": edl.get("motion", False),
        "broll": bool(broll_entries),
        "total_effects": len(seq),
        "counts": counts,
        "effects_sequence": seq
    }

    target_file = os.path.join(project_dir, out_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix="effects_log_", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
    os.replace(tmp_path, target_file)
    return log_data

def get_ngrams(seq, n=2):
    if len(seq) < n:
        return set()
    return set(tuple(seq[i:i+n]) for i in range(len(seq) - n + 1))

def compute_jaccard_similarity(seq1, seq2, n_gram_orders=(2, 3)):
    """Computes Jaccard similarity between two sequences using combined n-grams."""
    if seq1 == seq2:
        return 1.0
    
    ng1 = set()
    ng2 = set()
    for n in n_gram_orders:
        ng1 |= get_ngrams(seq1, n)
        ng2 |= get_ngrams(seq2, n)

    if not ng1 and not ng2:
        return 1.0
    if not ng1 or not ng2:
        return 0.0

    intersection = len(ng1 & ng2)
    union = len(ng1 | ng2)
    return float(intersection) / float(union)

def check_project_similarity(current_log, search_dir=None, threshold=0.70):
    """Compares current project's effects_log against other projects in search_dir."""
    current_proj = current_log.get("project", "")
    current_seq = current_log.get("effects_sequence", [])
    
    results = []
    if not search_dir or not os.path.exists(search_dir):
        return results

    for root, dirs, files in os.walk(search_dir):
        for f in files:
            if f == "effects_log.json":
                p_path = os.path.join(root, f)
                proj_name = os.path.basename(root)
                if proj_name == current_proj:
                    continue  # Skip self
                try:
                    with open(p_path, "r", encoding="utf-8") as pf:
                        other_log = json.load(pf)
                    other_seq = other_log.get("effects_sequence", [])
                    sim = compute_jaccard_similarity(current_seq, other_seq)
                    is_warning = sim > threshold
                    results.append({
                        "other_project": proj_name,
                        "similarity": round(sim, 4),
                        "warning": is_warning
                    })
                except Exception:
                    pass

    return results

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--search-dir", default=None)
    ap.add_argument("--threshold", type=float, default=0.70)
    args = ap.parse_args()

    project_dir = os.path.abspath(args.project)
    log_file = os.path.join(project_dir, "effects_log.json")
    if not os.path.exists(log_file):
        edl_file = os.path.join(project_dir, "edl_motion.json")
        if not os.path.exists(edl_file):
            edl_file = os.path.join(project_dir, "edl.json")
        with open(edl_file, "r", encoding="utf-8") as f:
            edl = json.load(f)
        broll_file = os.path.join(project_dir, "broll.json")
        broll = json.load(open(broll_file, "r", encoding="utf-8")) if os.path.exists(broll_file) else None
        log_data = build_effects_log(project_dir, edl, broll)
    else:
        with open(log_file, "r", encoding="utf-8") as f:
            log_data = json.load(f)

    search_dir = args.search_dir or os.path.dirname(project_dir)
    comparisons = check_project_similarity(log_data, search_dir, threshold=args.threshold)

    print(f"Effects log generated for {log_data['project']}: {log_data['total_effects']} events logged.")
    if comparisons:
        for comp in comparisons:
            msg = f"  vs {comp['other_project']}: Jaccard = {comp['similarity']:.3f}"
            if comp["warning"]:
                print(f"[WARNING] {msg} (> {args.threshold:.2f} NEAR-DUPLICATE TEMPLATE)")
            else:
                print(f"[OK] {msg}")
    else:
        print("  No other projects found for cross-comparison.")
