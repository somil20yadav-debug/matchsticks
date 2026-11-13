"""Script Auto-Draft & Beat-Splitter for StickmanHybrid.
Takes any raw narrative script and automatically:
1. Chops it into timed 2.5–3.5s visual beats.
2. Compiles LINES.tsv with sequential line IDs.
3. Crafts cinematic visual prompts in SHOTS.tsv with alternating composition spacing (left/right).
4. Assigns BOMA mascot references to key observer scenes.
5. Directs 3D camera moves (pull, push, orbit, drift, punch) in SCENES.tsv.
6. Generates STYLE.txt and SCRIPT.md.

Usage:
    python scripts/script_director.py <project_slug> (--file script.txt | --text "Raw text...")
"""

import csv, os, re, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def split_sentences_into_beats(text, target_words=9):
    """Splits raw text into natural 2.5-3.5 second spoken phrase chunks (7-12 words)."""
    # Clean text
    clean = re.sub(r'\s+', ' ', text).strip()
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', clean)

    beats = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence: continue
        words = sentence.split()

        if len(words) <= 12:
            beats.append(sentence)
        else:
            # Split long sentences on clauses or commas
            clauses = re.split(r'(?<=[,;:])\s+', sentence)
            cur_chunk = []
            for cl in clauses:
                cl_words = cl.split()
                if len(cur_chunk) + len(cl_words) <= 12:
                    cur_chunk.extend(cl_words)
                else:
                    if cur_chunk:
                        beats.append(" ".join(cur_chunk))
                    cur_chunk = cl_words
            if cur_chunk:
                beats.append(" ".join(cur_chunk))

    return [b for b in beats if b.strip()]


def auto_draft_project(slug, script_text, style_name="warm cinematic dark-sunset"):
    project_dir = os.path.join(BASE_DIR, slug)
    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "img", "clean"), exist_ok=True)

    beats = split_sentences_into_beats(script_text)
    print(f"=== Script Director: Splitting '{slug}' into {len(beats)} visual beats ===")

    # 1. LINES.tsv
    lines_tsv = os.path.join(project_dir, "LINES.tsv")
    with open(lines_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["id", "line"])
        for idx, b in enumerate(beats, 1):
            writer.writerow([f"{idx:02d}", b])
    print(f"[OK] LINES.tsv generated ({len(beats)} lines)")

    # 2. SHOTS.tsv
    shots_tsv = os.path.join(project_dir, "SHOTS.tsv")
    camera_moves = ["pull", "push", "driftR", "orbit", "driftL"]

    with open(shots_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["id", "ref", "prompt", "space"])
        
        for idx, b in enumerate(beats, 1):
            # Alternate BOMA appearances (intro, every 3rd beat, and conclusion)
            is_boma = (idx == 1 or idx == len(beats) or idx % 3 == 0)
            ref_str = "ref_boma" if is_boma else "-"

            # Alternate composition space for infographics
            space_str = "left" if idx % 2 == 1 else "right"

            # Create prompt
            prompt_core = b.rstrip(".,!?;:")
            if is_boma:
                prompt = f"BOMA witnessing {prompt_core}, cinematic atmosphere, wide 16:9 shot"
            else:
                prompt = f"Cinematic atmospheric scene of {prompt_core}, wide landscape, dramatic lighting"

            writer.writerow([str(idx), ref_str, prompt, space_str])
    print(f"[OK] SHOTS.tsv generated ({len(beats)} shots)")

    # 3. SCENES.tsv
    scenes_tsv = os.path.join(project_dir, "SCENES.tsv")
    with open(scenes_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["cue", "img", "text", "pos", "extra"])
        
        for idx, b in enumerate(beats, 1):
            cue = f"{idx:02d}.0"
            img_rel = f"img/s{idx:02d}.jpg"
            move = camera_moves[(idx - 1) % len(camera_moves)]

            # Check dramatic words for punch
            lower_b = b.lower()
            if any(w in lower_b for w in ["exploded", "blast", "suddenly", "shattered", "hit", "shook"]):
                extra = "fx:shake,punch@\"blast\""
            else:
                extra = f"move:{move}"

            writer.writerow([cue, img_rel, "", "", extra])
    print(f"[OK] SCENES.tsv generated ({len(beats)} scenes)")

    # 4. STYLE.txt
    style_txt = os.path.join(project_dir, "STYLE.txt")
    with open(style_txt, "w", encoding="utf-8") as f:
        f.write(f"look: {style_name}\n")
        f.write("cinematic dark-sunset palette, orange and amber glow, deep navy shadows, subtle film grain, wide cinematic shots. Every human is a pure stickman with a SOLID BLACK ROUND HEAD, big expressive white oval eyes, thin black line body, clean 2D vector cartoon style. No realistic humans, no photo faces, full-bleed backgrounds that fill the whole frame, 16:9, subject in the lower third, top left kept calm.\n")
    print(f"[OK] STYLE.txt generated")

    # 5. SCRIPT.md
    script_md = os.path.join(project_dir, "SCRIPT.md")
    est_duration_sec = len(beats) * 3.2
    est_min = int(est_duration_sec // 60)
    est_sec = int(est_duration_sec % 60)

    with open(script_md, "w", encoding="utf-8") as f:
        f.write(f"# Documentary Script: {slug.upper()}\n\n")
        f.write(f"- **Total Beats:** {len(beats)}\n")
        f.write(f"- **Estimated Duration:** ~{est_min}m {est_sec}s\n")
        f.write(f"- **Style:** {style_name}\n\n")
        f.write("## Voiceover Script\n\n")
        for idx, b in enumerate(beats, 1):
            f.write(f"**[{idx:02d}]** {b}\n\n")
    print(f"[OK] SCRIPT.md generated (~{est_min}m {est_sec}s estimated duration)")

    print(f"\n[DRAFT COMPLETE] Project '{slug}' is fully staged and ready for generation!")
    return project_dir


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/script_director.py <slug> (--text '...' | --file script.txt)")
        sys.exit(1)

    slug = sys.argv[1].lower()
    text = ""
    if "--file" in sys.argv:
        fidx = sys.argv.index("--file")
        with open(sys.argv[fidx + 1], "r", encoding="utf-8") as f:
            text = f.read()
    elif "--text" in sys.argv:
        tidx = sys.argv.index("--text")
        text = sys.argv[tidx + 1]

    auto_draft_project(slug, text)
