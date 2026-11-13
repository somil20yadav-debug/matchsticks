"""Viral Story & Hook Engine for StickmanHybrid.
Structures high-retention documentary scripts using proven YouTube retention curves:
1. The 30s Psychological Hook (Mystery / Anomaly / High Stakes)
2. The Incident & Eyewitness Timeline
3. The Investigation & Dead Ends
4. The Climax & Modern Scientific Truth
5. The Philosophical Sign-off (BOMA Outro)

Automatically outputs LINES.tsv, SHOTS.tsv, SCENES.tsv, STYLE.txt, and SCRIPT.md.

Usage:
    python scripts/story_engine.py <slug> --topic "Topic description" [--title "Title"]
    python scripts/story_engine.py <slug> --file script.txt
"""

import csv, json, os, re, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


STYLE_PRESETS = {
    "cinematic": {
        "look": "hyper-cinematic documentary",
        "prompt_suffix": ", 35mm anamorphic photography, volumetric lighting, photorealistic Unreal Engine 5 render, award-winning cinematography, atmospheric fog, 8k resolution, IMAX aspect ratio",
        "style_desc": "Cinematic 35mm documentary photography, deep focal depth, moody natural lighting, atmospheric haze, photorealistic real-world environments. No stickmen, pure cinematic realism."
    },
    "noir": {
        "look": "dark mystery investigative noir",
        "prompt_suffix": ", high-contrast chiaroscuro shadows, dramatic rim lighting, moody neo-noir atmosphere, 35mm film grain, David Fincher color grade, cinematic suspense",
        "style_desc": "High-contrast chiaroscuro lighting, deep mysterious shadows, desaturated cool tones with amber accents, intense forensic investigative atmosphere."
    },
    "anime": {
        "look": "cinematic anime landscape",
        "prompt_suffix": ", Makoto Shinkai aesthetic, Studio Ghibli inspired, vibrant painted sky, detailed background art, glowing light shafts, masterpiece digital illustration",
        "style_desc": "Cinematic Japanese animation aesthetic, vibrant skies, hand-painted background depth, glowing luminous lighting."
    },
    "business": {
        "look": "modern corporate tech explainer",
        "prompt_suffix": ", sleek minimalist architectural space, clean studio lighting, high-tech glass reflections, Bloomberg / Vox explainer aesthetic, premium commercial photography",
        "style_desc": "Clean modern tech aesthetic, architectural glass, sleek minimalist lighting, sophisticated neutral tones."
    },
    "hybrid": {
        "look": "minimalist silhouette hybrid",
        "prompt_suffix": ", dramatic wide cinematic landscape with minimalist solid black silhouette characters, expressive cartoon eyes, volumetric sunset lighting, 8k documentary background",
        "style_desc": "Atmospheric cinematic environments with minimalist 2D silhouette characters, high contrast and expressive storytelling."
    }
}


def build_retention_story(slug, topic, title=None, style_preset="cinematic"):
    """Generates an algorithmic high-retention documentary script based on proven YouTube pacing."""
    title = title or topic.title()
    preset = STYLE_PRESETS.get(style_preset.lower(), STYLE_PRESETS["cinematic"])

    # Story archetypes built for stickman hybrid documentaries
    script_beats = [
        # Act 1: The 30s Hook (0:00 - 0:30)
        f"In history, some events defy every law of science.",
        f"On a calm morning, something happened that still terrifies investigators.",
        f"Within seconds, everything we thought we understood vanished completely.",
        f"And to this day, no official report can fully explain it.",

        # Act 2: The Incident & Eyewitnesses (0:30 - 1:15)
        f"The story begins with {topic}.",
        f"Witnesses reported seeing a strange anomaly in the distance.",
        f"At first, everyone assumed it was a routine occurrence.",
        f"Then, the instruments began behaving erratically.",
        f"Radio contact was suddenly lost, replaced only by static.",

        # Act 3: The Investigation & Dead Ends (1:15 - 2:00)
        f"Rescue teams were deployed immediately across hundreds of miles.",
        f"What they found at the site was completely baffling.",
        f"There was no wreckage, no debris, and zero signs of life.",
        f"Top researchers spent months analyzing the final recorded coordinates.",
        f"Every conventional hypothesis led directly to an impossible dead end.",

        # Act 4: The Climax & Scientific Explanation (2:00 - 3:00)
        f"Decades later, modern technology finally uncovered a hidden clue.",
        f"Advanced satellite scans revealed an invisible atmospheric phenomenon.",
        f"Under extreme geological conditions, nature can create violent shockwaves.",
        f"The forces released were equivalent to millions of tons of pressure.",
        f"What people witnessed wasn't magic—it was Earth's most dangerous secret.",

        # Act 5: The Outro (3:00 - 3:30)
        f"Yet, even with modern science, several critical questions remain unanswered.",
        f"Some files are still classified, locked away from the public.",
        f"And whenever you look into the horizon, remember this story.",
        f"Because what happened once... could happen again."
    ]

    return title, script_beats


def save_story_project(slug, beats, title=None, style_preset="cinematic"):
    project_dir = os.path.join(BASE_DIR, slug)
    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "img", "clean"), exist_ok=True)

    title = title or slug.replace("_", " ").title()
    preset = STYLE_PRESETS.get(style_preset.lower(), STYLE_PRESETS["cinematic"])
    print(f"=== Story Engine: Generating High-Retention Project '{slug}' [{style_preset.upper()}] ({len(beats)} beats) ===")

    # 1. LINES.tsv
    lines_tsv = os.path.join(project_dir, "LINES.tsv")
    with open(lines_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["id", "line"])
        for idx, b in enumerate(beats, 1):
            writer.writerow([f"{idx:02d}", b])
    print(f"[OK] LINES.tsv written ({len(beats)} lines)")

    # 2. SHOTS.tsv
    shots_tsv = os.path.join(project_dir, "SHOTS.tsv")
    with open(shots_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["id", "ref", "prompt", "space"])

        for idx, b in enumerate(beats, 1):
            space_str = "left" if idx % 2 == 1 else "right"
            prompt_core = b.rstrip(".,!?;:")

            if style_preset == "hybrid":
                is_hero = (idx == 1 or idx == 3 or idx == len(beats) or idx % 3 == 0)
                ref_str = "ref_hero" if is_hero else "-"
                hero_prefix = "Silhouette explorer witnessing " if is_hero else ""
                prompt = f"{hero_prefix}{prompt_core}{preset['prompt_suffix']}"
            else:
                ref_str = "-"
                prompt = f"{prompt_core}{preset['prompt_suffix']}"

            writer.writerow([str(idx), ref_str, prompt, space_str])
    print(f"[OK] SHOTS.tsv written ({len(beats)} badass cinematic shots)")

    # 3. SCENES.tsv
    scenes_tsv = os.path.join(project_dir, "SCENES.tsv")
    camera_moves = ["pull", "push", "driftR", "orbit", "driftL"]

    with open(scenes_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["cue", "img", "text", "pos", "extra"])

        for idx, b in enumerate(beats, 1):
            cue = f"{idx:02d}.0"
            img_rel = f"img/s{idx:02d}.jpg"
            move = camera_moves[(idx - 1) % len(camera_moves)]

            lower_b = b.lower()
            if any(w in lower_b for w in ["exploded", "blast", "vanished", "suddenly", "shook", "impossible"]):
                extra = "fx:shake,punch@\"climax\""
            else:
                extra = f"move:{move}"

            writer.writerow([cue, img_rel, "", "", extra])
    print(f"[OK] SCENES.tsv written ({len(beats)} scenes)")

    # 4. STYLE.txt
    style_txt = os.path.join(project_dir, "STYLE.txt")
    with open(style_txt, "w", encoding="utf-8") as f:
        f.write(f"look: {preset['look']}\n")
        f.write(f"{preset['style_desc']}\n")
    print(f"[OK] STYLE.txt written ({style_preset.upper()} style preset)")

    # 5. SCRIPT.md
    script_md = os.path.join(project_dir, "SCRIPT.md")
    est_duration_sec = len(beats) * 3.2
    est_min = int(est_duration_sec // 60)
    est_sec = int(est_duration_sec % 60)

    with open(script_md, "w", encoding="utf-8") as f:
        f.write(f"# Documentary Script: {title}\n\n")
        f.write(f"- **Project Slug:** `{slug}`\n")
        f.write(f"- **Total Narrative Beats:** {len(beats)}\n")
        f.write(f"- **Target Video Duration:** ~{est_min}m {est_sec}s\n")
        f.write(f"- **Visual Palette:** {preset['look'].title()}\n\n")
        f.write("## 🎬 Narration Script Breakdown\n\n")
        for idx, b in enumerate(beats, 1):
            f.write(f"**[{idx:02d}]** {b}\n\n")
    print(f"[OK] SCRIPT.md written (~{est_min}m {est_sec}s target duration)")

    print(f"\n[STORY COMPLETE] Project '{slug}' successfully staged with high-retention narrative structure!")
    return project_dir


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/story_engine.py <slug> --topic 'Topic description' [--title 'Title']")
        sys.exit(1)

    slug = sys.argv[1].lower()
    topic = ""
    title = None

    if "--topic" in sys.argv:
        tidx = sys.argv.index("--topic")
        topic = sys.argv[tidx + 1]
    if "--title" in sys.argv:
        title_idx = sys.argv.index("--title")
        title = sys.argv[title_idx + 1]
    elif "--file" in sys.argv:
        fidx = sys.argv.index("--file")
        with open(sys.argv[fidx + 1], "r", encoding="utf-8") as f:
            topic = f.read()

    style_preset = "cinematic"
    if "--style" in sys.argv:
        style_preset = sys.argv[sys.argv.index("--style") + 1]

    title, beats = build_retention_story(slug, topic, title=title, style_preset=style_preset)
    save_story_project(slug, beats, title=title, style_preset=style_preset)


if __name__ == "__main__":
    main()
