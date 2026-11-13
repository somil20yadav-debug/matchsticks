"""B-roll planner and human approval gate.
1. Target scenes: duration >= 4.0s only. Max 1 cutaway per such scene.
2. Cut in on trigger word timestamp, duration 1.5 - 3.0s, ending on or before scene cut.
3. No overlap with sticker pops (0.5s margin), punch-ins (0.5s margin), or first 3.0s.
4. Reuse order: (a) existing picked images/elements whose tags match trigger word;
               (b) unmatched triggers emit new Flow prompts in broll.json and wait for --approve-broll.
5. Deterministic via seed.
"""
import csv, json, math, os, re, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edl_planner import score_word

STOP_WORDS = {
    "a", "about", "above", "across", "after", "again", "against", "all", "almost", "along",
    "already", "also", "although", "always", "among", "an", "and", "another", "any", "anybody",
    "anyone", "anything", "anywhere", "are", "around", "as", "at", "back", "be", "became",
    "because", "become", "becomes", "becoming", "been", "before", "behind", "being", "below",
    "between", "both", "built", "but", "by", "called", "came", "can", "cannot", "come", "could",
    "did", "do", "does", "doing", "done", "down", "during", "each", "either", "else", "even",
    "ever", "every", "everybody", "everyone", "everything", "everywhere", "few", "first", "for",
    "form", "found", "from", "get", "give", "go", "goes", "going", "gone", "got", "grows",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "last",
    "least", "less", "let", "lies", "like", "likely", "made", "make", "makes", "many", "may",
    "me", "might", "more", "most", "much", "must", "my", "myself", "near", "neither", "never",
    "new", "next", "no", "nobody", "none", "noone", "nor", "not", "nothing", "now", "nowhere",
    "of", "off", "often", "on", "once", "one", "only", "onto", "or", "other", "others", "our",
    "ours", "ourselves", "out", "over", "own", "per", "perhaps", "probably", "quite", "rather",
    "said", "same", "say", "says", "see", "seem", "seemed", "seeming", "seems", "several",
    "shall", "she", "should", "since", "so", "some", "somebody", "someone", "something",
    "somewhere", "still", "such", "swept", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "therefore", "these", "they", "think", "this", "those",
    "though", "through", "throughout", "thru", "thus", "to", "together", "too", "toward",
    "towards", "under", "until", "up", "upon", "us", "used", "uses", "using", "very", "was",
    "way", "we", "well", "went", "were", "what", "whatever", "when", "whence", "whenever",
    "where", "whereafter", "whereas", "whereby", "wherein", "whereupon", "wherever", "whether",
    "which", "while", "whither", "who", "whoever", "whole", "whom", "whose", "why", "will",
    "with", "within", "without", "would", "yet", "you", "your", "yours", "yourself", "yourselves",
    "simple", "rough", "small", "big", "vast", "deep", "dated", "known", "seen", "felt"
}

def clean_token(w):
    return re.sub(r"[^\w]", "", w).strip().lower()

def stem_word(w):
    w = clean_token(w)
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        return w[:-1]
    return w

def build_asset_catalog(project_dir):
    """Builds keyword-to-asset mapping from existing SHOTS.tsv and ELEMENTS.tsv using exact lemmas."""
    catalog = {}
    shots_file = os.path.join(project_dir, "SHOTS.tsv")
    elements_file = os.path.join(project_dir, "ELEMENTS.tsv")

    if os.path.exists(elements_file):
        for r in csv.DictReader(open(elements_file, encoding="utf-8"), delimiter="\t"):
            eid = f"{int(r['id']):02d}"
            cut_path = f"elements/cut/{eid}.png"
            desc = r.get("object", "").lower()
            for token in re.findall(r"\b[a-z]{3,}\b", desc):
                if token not in STOP_WORDS:
                    stem = stem_word(token)
                    catalog.setdefault(stem, []).append((cut_path, f"element:{eid}"))
                    catalog.setdefault(token, []).append((cut_path, f"element:{eid}"))

    if os.path.exists(shots_file):
        for r in csv.DictReader(open(shots_file, encoding="utf-8"), delimiter="\t"):
            sid = f"{int(r['id']):02d}"
            img_path = f"img/s{sid}.jpg"
            prompt = r.get("prompt", "").lower()
            for token in re.findall(r"\b[a-z]{3,}\b", prompt):
                if token not in STOP_WORDS:
                    stem = stem_word(token)
                    catalog.setdefault(stem, []).append((img_path, f"shot:{sid}"))
                    catalog.setdefault(token, []).append((img_path, f"shot:{sid}"))

    return catalog

def plan_broll(project_dir, edl, seed_val=42, out_path="broll.json"):
    """Plans B-roll cutaways for scenes >= 4.0s."""
    rng = np.random.default_rng(np.random.PCG64(seed_val))
    scenes = edl.get("scenes", [])
    total_dur = edl.get("total_duration", 0.0)
    punch_ins = edl.get("punch_ins", [])
    all_cuts = [s["t0"] for s in scenes] + [total_dur]
    all_pops = [o["t"] for s in scenes for o in s.get("overlays", [])]

    # Load words
    words_file = os.path.join(project_dir, "WORDS.tsv")
    words = list(csv.DictReader(open(words_file, encoding="utf-8"), delimiter="\t"))

    catalog = build_asset_catalog(project_dir)
    broll_entries = []

    for sc in scenes:
        dur = sc["duration"]
        if dur < 4.0:
            continue  # Rule: B-roll applies ONLY to scenes >= 4.0s

        t0, t1 = sc["t0"], sc["t1"]
        sc_words = [w for w in words if t0 <= float(w["start"]) < t1]
        if not sc_words:
            continue

        candidates = []
        for w in sc_words:
            w_start = float(w["start"])
            token = clean_token(w["word"])
            if len(token) < 3 or w_start < 3.0 or token in STOP_WORDS:
                continue

            # Must be at least 0.5s after scene start
            if (w_start - t0) < 0.5:
                continue

            # Available duration before scene cut
            avail_before_cut = t1 - w_start
            if avail_before_cut < 1.5:
                continue

            # Find next pop
            future_pops = [pop for pop in all_pops if pop > w_start]
            next_pop = min(future_pops) if future_pops else total_dur
            max_dur_pop = next_pop - 0.5 - w_start
            if max_dur_pop < 1.5:
                continue

            # Check overlap with previous pops within 0.5s
            if any(abs(w_start - pop) < 0.5 for pop in all_pops):
                continue

            # Find next punch-in
            future_pis = [p["t_in"] for p in punch_ins if p["t_in"] > w_start]
            next_pi = min(future_pis) if future_pis else total_dur
            max_dur_pi = next_pi - 0.5 - w_start
            if max_dur_pi < 1.5:
                continue

            # Check overlap with previous punch-ins within 0.5s
            if any(max(w_start - 0.5, p["t_in"] - 0.5) < min(w_start + 1.5 + 0.5, p["t_out"] + 0.5) for p in punch_ins):
                continue

            max_dur = min(3.0, avail_before_cut, max_dur_pop, max_dur_pi)
            if max_dur < 1.5:
                continue

            # Match against catalog (exact or stemmed)
            matched_asset = None
            tag_name = None
            stem = stem_word(token)
            if token in catalog:
                matched_asset, tag_name = catalog[token][0]
            elif stem in catalog:
                matched_asset, tag_name = catalog[stem][0]

            # Priority score: asset reuse = 3.0, capitalized proper noun / place = 2.0, concrete noun = 1.0
            is_capital = w["word"][0].isupper() if w["word"] else False
            score = (3.0 if matched_asset else 0.0) + (2.0 if is_capital else 1.0)

            candidates.append({
                "word": w["word"],
                "clean": token,
                "start": w_start,
                "max_dur": max_dur,
                "matched_asset": matched_asset,
                "tag": tag_name,
                "score": score
            })

        if not candidates:
            continue

        # Sort candidates by score descending, then longest duration headroom
        candidates.sort(key=lambda c: (c["score"], c["max_dur"]), reverse=True)
        chosen = candidates[0]

        t_in = chosen["start"]
        max_possible = min(3.0, chosen["max_dur"])

        # Jittered duration in [1.5, max_possible]
        low_dur = 1.5
        high_dur = min(2.6, max_possible)
        if high_dur <= low_dur:
            dur_target = max_possible
        else:
            dur_target = float(rng.uniform(low_dur, high_dur))
        # If ending within 0.35s of scene cut, snap to scene cut for a clean edit
        if abs((t_in + dur_target) - t1) < 0.35 and (t1 - t_in) <= 3.0:
            target_dur = round(t1 - t_in, 3)
        else:
            target_dur = round(dur_target, 2)

        t_out = round(t_in + target_dur, 3)

        if chosen["matched_asset"]:
            entry = {
                "id": f"broll_{len(broll_entries)+1:02d}",
                "scene_cue": sc["cue"],
                "trigger_word": chosen["word"],
                "t_in": round(t_in, 3),
                "t_out": t_out,
                "duration": round(t_out - t_in, 3),
                "source": "reuse",
                "asset": chosen["matched_asset"],
                "reuse_tag": chosen["tag"],
                "prompt": None
            }
        else:
            if chosen["clean"] in ("million", "thousand", "years"):
                prompt_str = f"Documentary cutaway shot illustrating early prehistoric landscape one {chosen['clean']} years ago in ancient maritime context, painted style, no text, no people."
            else:
                prompt_str = f"Documentary cutaway shot illustrating {chosen['clean']} in ancient maritime context, painted style, no text, no people."
            entry = {
                "id": f"broll_{len(broll_entries)+1:02d}",
                "scene_cue": sc["cue"],
                "trigger_word": chosen["word"],
                "t_in": round(t_in, 3),
                "t_out": t_out,
                "duration": round(t_out - t_in, 3),
                "source": "new",
                "asset": None,
                "reuse_tag": None,
                "prompt": prompt_str
            }

        broll_entries.append(entry)

    target_file = os.path.join(project_dir, out_path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix="broll_", suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(broll_entries, f, indent=2)
    os.replace(tmp_path, target_file)
    return broll_entries

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="broll.json")
    args = ap.parse_args()

    edl_file = os.path.join(args.project, "edl_motion.json")
    if not os.path.exists(edl_file):
        from edl_planner import build_edl
        edl = build_edl(args.project, seed_val=args.seed, motion=True)
    else:
        with open(edl_file, "r", encoding="utf-8") as f:
            edl = json.load(f)

    broll = plan_broll(args.project, edl, seed_val=args.seed, out_path=args.out)
    print(f"Emitted {len(broll)} B-roll cutaway entries to {args.out}")
