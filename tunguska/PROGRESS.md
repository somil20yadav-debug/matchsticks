# Progress: The Day Something Flattened Siberia (tunguska)

- **Topic:** The Tunguska Event (1908 Siberian forest explosion)
- **Language:** English
- **Total Duration:** 5:22.4 (322.45s, 56 scenes, 9,673 frames @ 30 fps)
- **Voice:** English documentary narration (Kokoro af_heart, speed 1.0)
- **Look:** Warm cinematic dark-sunset / amber-navy palette (`STYLE.txt`)
- **Cast:** BOMA (mascot), Evenki herder, Siberian trader, Leonid Kulik, Soviet scientist, Londoners, Stickman Alien, Nikola Tesla

## Completed Milestones
- [x] **Stage 0: Project Setup:** Directory, `STYLE.txt`, `SCRIPT.md`, `LINES.tsv`, and tracking structure.
- [x] **Stage 1: Google Flow Sheets:**
  - Sheet A: BOMA Peeks (green screen keyed -> 12 transparent PNGs with die-cut white borders & shadows)
  - Sheet B: Stickman Cast (green screen keyed -> 8 full-body characters: herder, trader, Kulik, scientist, Londoners, alien, Tesla)
  - Sheet C: Prop Stickers (black screen keyed -> 22 glowing props: fireball, shockwave, shattered window, telescope, etc.)
- [x] **Stage 2: Narration & Alignment:**
  - Complete 56-line Kokoro narration audio (`VO.wav`, 322.45s / 5.37 mins)
  - Exact word timestamps generated (`WORDS.tsv`, 760 words)
- [x] **Stage 3: EDL & Directives:**
  - `SHOTS.tsv` (48 shots) and `SCENES.tsv` (100 rows) compiled with parallax, stickers, peeks, counters, and punch-ins.
- [x] **Stage 4: Act 1 Render & Engine Stabilization:**
  - Fixed full-bleed 1920x1080 canvas fit (eliminated upper-left squishing and border reflections).
  - Cleaned all Google Flow Gemini watermarks via harmonic + Telea inpainting.
- [x] **Stage 5: Full Film Render & Verification:**
  - All 48 scene backgrounds generated via Google Flow (`img/s01.jpg` – `s56.jpg`) and cleaned in `img/clean/`.
  - Rendered complete video: `tunguska.mp4` (117.2 MB, 322.45s, 56 scenes).
  - 47 active multi-plane depth parallax scenes (`pull`: 14, `push`: 10, `driftR`: 7, `orbit`: 9, `driftL`: 7) with 0 fallbacks.
  - Complete 56-milestone contact sheet generated (`qc_full.jpg`).
