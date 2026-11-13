"""Interactive Local QC Player Builder for StickmanHybrid.
Generates a standalone, beautiful HTML5 review studio ('qc_player.html') inside any project.
Allows instant, zero-render scrubbing across all scenes with synchronized audio,
stickers, captions, and camera directive inspection.

Usage:
    python scripts/qc_player_builder.py <project_slug>
"""

import os, sys, json, csv, glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_qc_player(slug):
    project_dir = os.path.join(BASE_DIR, slug)
    if not os.path.exists(project_dir):
        sys.exit(f"[ERROR] Project '{slug}' not found at {project_dir}")

    edl_path = os.path.join(project_dir, "edl.json")
    scenes_tsv = os.path.join(project_dir, "SCENES.tsv")
    words_tsv = os.path.join(project_dir, "WORDS.tsv")
    lines_tsv = os.path.join(project_dir, "LINES.tsv")
    clean_img_dir = os.path.join(project_dir, "img", "clean")
    html_out = os.path.join(project_dir, "qc_player.html")

    scenes_data = []
    total_duration = 300.0

    if os.path.exists(edl_path):
        with open(edl_path, "r", encoding="utf-8") as f:
            edl = json.load(f)
        total_duration = edl.get("total_duration", 300.0)
        for sc in edl.get("scenes", []):
            img_rel = sc.get("img", "")
            base_stem = os.path.splitext(os.path.basename(img_rel))[0]
            clean_png = os.path.join(project_dir, "img", "clean", f"{base_stem}.png")
            clean_jpg = os.path.join(project_dir, "img", "clean", f"{base_stem}.jpg")
            if os.path.exists(clean_png):
                img_src = f"img/clean/{base_stem}.png"
            elif os.path.exists(clean_jpg):
                img_src = f"img/clean/{base_stem}.jpg"
            elif os.path.exists(os.path.join(project_dir, img_rel)):
                img_src = img_rel
            else:
                img_src = f"img/{base_stem}.jpg"

            scenes_data.append({
                "idx": sc.get("scene_idx", 0) + 1,
                "cue": sc.get("cue", ""),
                "t0": sc.get("t0", 0.0),
                "t1": sc.get("t1", 0.0),
                "duration": round(sc.get("duration", 0.0), 2),
                "img": img_src,
                "move": sc.get("base_effect", {}).get("move", "static"),
                "text": sc.get("text", ""),
                "overlays": [ov.get("img", "") for ov in sc.get("overlays", [])]
            })

    # Words data for synced live captions
    words_data = []
    if os.path.exists(words_tsv):
        with open(words_tsv, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                try:
                    words_data.append({
                        "word": r.get("word", ""),
                        "start": float(r.get("start", 0)),
                        "end": float(r.get("end", 0))
                    })
                except ValueError:
                    continue

    # Build standalone HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>StickmanHybrid QC Studio — {slug.upper()}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }}
        #main {{
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 20px;
            gap: 15px;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
        }}
        h1 {{ font-size: 20px; color: #58a6ff; font-weight: 600; }}
        .badge {{ background: #238636; color: white; padding: 3px 8px; border-radius: 12px; font-size: 12px; }}
        
        #viewport {{
            flex: 1;
            background: #000;
            border-radius: 8px;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }}
        #scene-img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            transition: transform 0.3s ease-out;
        }}
        #caption-overlay {{
            position: absolute;
            bottom: 30px;
            left: 5%;
            right: 5%;
            text-align: center;
            font-size: 24px;
            font-weight: 700;
            color: #fff;
            text-shadow: 0 2px 8px rgba(0,0,0,0.9), 0 0 20px rgba(0,0,0,0.8);
            background: rgba(13, 17, 23, 0.7);
            padding: 10px 20px;
            border-radius: 8px;
            backdrop-filter: blur(4px);
        }}
        .active-word {{ color: #ffd33d; transform: scale(1.1); display: inline-block; }}
        
        #meta-overlay {{
            position: absolute;
            top: 15px;
            left: 15px;
            background: rgba(0,0,0,0.75);
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 13px;
            line-height: 1.5;
            border: 1px solid #30363d;
        }}
        .tag {{ color: #79c0ff; font-weight: 600; }}

        #controls {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: #161b22;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #30363d;
        }}
        #timeline-container {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        #scrubber {{
            flex: 1;
            cursor: pointer;
            accent-color: #58a6ff;
        }}
        .btn {{
            background: #21262d;
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }}
        .btn:hover {{ background: #30363d; color: white; }}
        .btn.active {{ background: #238636; border-color: #2ea043; color: white; }}
        
        #sidebar {{
            width: 380px;
            background: #161b22;
            border-left: 1px solid #30363d;
            display: flex;
            flex-direction: column;
        }}
        #sidebar-header {{
            padding: 15px;
            border-bottom: 1px solid #30363d;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
        }}
        #scene-list {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .scene-card {{
            display: flex;
            gap: 10px;
            padding: 8px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .scene-card:hover {{ border-color: #58a6ff; }}
        .scene-card.active {{ border-color: #238636; background: #16241b; }}
        .scene-thumb {{
            width: 90px;
            height: 50px;
            object-fit: cover;
            border-radius: 4px;
            background: #21262d;
        }}
        .scene-info {{
            flex: 1;
            font-size: 12px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 3px;
        }}
        .scene-num {{ font-weight: 700; color: #58a6ff; }}
    </style>
</head>
<body>
    <div id="main">
        <header>
            <h1>🎬 StickmanHybrid QC Studio: <span style="color:#fff">{slug.upper()}</span></h1>
            <div>
                <span class="badge">{len(scenes_data)} SCENES</span>
                <span class="badge" style="background:#1f6feb">{int(total_duration // 60)}m {int(total_duration % 60)}s</span>
            </div>
        </header>

        <div id="viewport">
            <img id="scene-img" src="" alt="Scene View">
            <div id="meta-overlay">
                <div>Scene: <span class="tag" id="meta-idx">-</span> | Cue: <span class="tag" id="meta-cue">-</span></div>
                <div>Move: <span class="tag" id="meta-move">-</span> | Duration: <span class="tag" id="meta-dur">-</span></div>
            </div>
            <div id="caption-overlay">Loading captions...</div>
        </div>

        <div id="controls">
            <div id="timeline-container">
                <button class="btn" id="play-btn">▶ Play</button>
                <span id="time-display" style="font-family: monospace; font-size: 13px;">00:00 / 00:00</span>
                <input type="range" id="scrubber" min="0" max="{total_duration}" step="0.1" value="0">
                <audio id="audio-player" src="mix.wav" preload="auto"></audio>
            </div>
        </div>
    </div>

    <div id="sidebar">
        <div id="sidebar-header">
            <span>Scenes Directory ({len(scenes_data)})</span>
            <span style="font-size: 12px; color: #8b949e;">Click to Jump</span>
        </div>
        <div id="scene-list"></div>
    </div>

    <script>
        const scenes = {json.dumps(scenes_data)};
        const words = {json.dumps(words_data)};
        const totalDuration = {total_duration};

        const audio = document.getElementById('audio-player');
        const playBtn = document.getElementById('play-btn');
        const scrubber = document.getElementById('scrubber');
        const timeDisplay = document.getElementById('time-display');
        const sceneImg = document.getElementById('scene-img');
        const metaIdx = document.getElementById('meta-idx');
        const metaCue = document.getElementById('meta-cue');
        const metaMove = document.getElementById('meta-move');
        const metaDur = document.getElementById('meta-dur');
        const captionOverlay = document.getElementById('caption-overlay');
        const sceneList = document.getElementById('scene-list');

        let currentScene = null;

        // Populate sidebar scenes
        scenes.forEach((sc, i) => {{
            const card = document.createElement('div');
            card.className = 'scene-card';
            card.id = `card-${{sc.idx}}`;
            card.onclick = () => jumpToTime(sc.t0);
            card.innerHTML = `
                <img class="scene-thumb" src="${{sc.img}}" onerror="this.src='';">
                <div class="scene-info">
                    <span class="scene-num">Scene #${{sc.idx}} (${{sc.cue}})</span>
                    <span>Move: <b>${{sc.move}}</b> (${{sc.duration}}s)</span>
                    <span style="color:#8b949e; font-family: monospace;">${{formatTime(sc.t0)}} - ${{formatTime(sc.t1)}}</span>
                </div>
            `;
            sceneList.appendChild(card);
        }});

        function formatTime(s) {{
            const m = Math.floor(s / 60);
            const sec = Math.floor(s % 60);
            return `${{m.toString().padStart(2, '0')}}:${{sec.toString().padStart(2, '0')}}`;
        }}

        function updateSceneView(time) {{
            const match = scenes.find(s => time >= s.t0 && time < s.t1) || scenes[scenes.length - 1];
            if (match && match !== currentScene) {{
                currentScene = match;
                sceneImg.src = match.img;
                metaIdx.innerText = `#${{match.idx}}`;
                metaCue.innerText = match.cue;
                metaMove.innerText = match.move.toUpperCase();
                metaDur.innerText = `${{match.duration}}s`;

                document.querySelectorAll('.scene-card').forEach(c => c.classList.remove('active'));
                const activeCard = document.getElementById(`card-${{match.idx}}`);
                if (activeCard) {{
                    activeCard.classList.add('active');
                    activeCard.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
                }}
            }}

            // Word-level dynamic captioning
            const activeWordIdx = words.findIndex(w => time >= w.start && time <= w.end);
            if (activeWordIdx !== -1) {{
                const startWindow = Math.max(0, activeWordIdx - 3);
                const endWindow = Math.min(words.length, activeWordIdx + 4);
                const chunk = words.slice(startWindow, endWindow).map((w, idx) => {{
                    const isCurrent = (startWindow + idx) === activeWordIdx;
                    return isCurrent ? `<span class="active-word">${{w.word}}</span>` : w.word;
                }}).join(' ');
                captionOverlay.innerHTML = chunk;
            }} else {{
                captionOverlay.innerText = currentScene ? (currentScene.text || '') : '';
            }}
        }}

        function jumpToTime(t) {{
            audio.currentTime = t;
            scrubber.value = t;
            timeDisplay.innerText = `${{formatTime(t)}} / ${{formatTime(totalDuration)}}`;
            updateSceneView(t);
        }}

        playBtn.onclick = () => {{
            if (audio.paused) {{
                audio.play().catch(() => {{}});
                playBtn.innerText = '⏸ Pause';
                playBtn.classList.add('active');
            }} else {{
                audio.pause();
                playBtn.innerText = '▶ Play';
                playBtn.classList.remove('active');
            }}
        }};

        audio.ontimeupdate = () => {{
            const t = audio.currentTime;
            scrubber.value = t;
            timeDisplay.innerText = `${{formatTime(t)}} / ${{formatTime(totalDuration)}}`;
            updateSceneView(t);
        }};

        scrubber.oninput = () => {{
            const t = parseFloat(scrubber.value);
            audio.currentTime = t;
            timeDisplay.innerText = `${{formatTime(t)}} / ${{formatTime(totalDuration)}}`;
            updateSceneView(t);
        }};

        // Initialize at 0
        if (scenes.length > 0) updateSceneView(0);
        timeDisplay.innerText = `00:00 / ${{formatTime(totalDuration)}}`;
    </script>
</body>
</html>"""

    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[SUCCESS] Interactive QC Studio compiled: {html_out}")
    print(f"          Open in your browser to inspect all {len(scenes_data)} scenes with live audio sync!")
    return html_out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/qc_player_builder.py <project_slug>")
        sys.exit(1)
    build_qc_player(sys.argv[1])
