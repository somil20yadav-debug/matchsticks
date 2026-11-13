# Matchsticks 🎬

> ### **Created & Developed by [Somil Yadav](https://github.com/somil20yadav-debug)**  
> *From an idea or script to a television-grade documentary in one command.*

[![Author](https://img.shields.io/badge/Author-Somil%20Yadav-blue.svg?style=flat&logo=github)](https://github.com/somil20yadav-debug)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Zero Cost](https://img.shields.io/badge/TTS-Free%20%2F%20Local-orange.svg)](#step-3-generate-voiceover-narration-free)
[![Image Gen](https://img.shields.io/badge/Images-Free%20Web%20%2F%20Gemini%20%2F%20Local-yellow.svg)](#step-2-generate-images-zero-manual-work)
[![Format](https://img.shields.io/badge/Export-1080p%20Master%20%2B%209%3A16%20Shorts-red.svg)](#step-7-render-your-video)

---

## 💡 What is Matchsticks?

**Matchsticks** is an open-source, local-first AI video studio. It automates the entire video creation pipeline:
1. Takes a topic or script and slices it into **2.5s high-retention storytelling beats**.
2. **Generates cinematic scene images automatically** (using free web endpoints, Gemini, or local GPUs).
3. **Generates natural voiceovers for free** (using Edge-TTS or Kokoro).
4. **Aligns word timestamps** using local Whisper speech recognition.
5. **Adds cinematic sound design** (procedural hits, whooshes, and speech ducking).
6. **Renders full 1080p master documentaries** with 3D camera depth or **9:16 vertical shorts (Opus Clip style)** with kinetic captions.

**Zero paid API lock-in. Zero monthly subscriptions.**

---

## 🔰 Absolute Beginner Guide (No Coding or Git Experience Required)

If you have never used GitHub or terminal before, follow these simple steps to get started in under 5 minutes:

### Step 0: Prerequisites (Only Do This Once)

#### 1. Install Python (Version 3.10 or newer)
* Download it from 👉 [python.org](https://www.python.org/downloads/)
* ⚠️ **IMPORTANT**: On the first screen of the installer, check the box that says **"Add python.exe to PATH"** before clicking Install.

#### 2. Install FFmpeg (Handles video & audio rendering)
* **Windows (Fastest)**: Open PowerShell and run:
  ```powershell
  winget install Gyan.FFmpeg
  ```
  *(Or download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/) and add its `bin` folder to your System PATH).*
* **Mac**: Open Terminal and run: `brew install ffmpeg`
* **Linux**: `sudo apt install ffmpeg`

---

### Step 1: Download Matchsticks

#### Option A (For Beginners — No Git Required):
1. Click the green **`<> Code`** button at the top of this GitHub page.
2. Click **"Download ZIP"**.
3. Extract the downloaded `.zip` folder to your computer (e.g. `C:\matchsticks` or your Desktop).

#### Option B (Using Git):
```bash
git clone https://github.com/somil20yadav-debug/matchsticks.git
cd matchsticks
```

---

### Step 2: Open Terminal & Install Dependencies

1. **Open your Terminal**:
   * **Windows**: Press `Win + R`, type `powershell`, and hit **Enter**.
   * Navigate into your downloaded folder:
     ```powershell
     cd C:\path\to\matchsticks
     ```
2. **Install the required packages** (takes ~1 minute):
   ```bash
   pip install -r requirements.txt
   ```

You are ready! Let's make your first video.

---

## 🎬 How to Make a Video in 7 Simple Steps

To make a video, you choose a single **keyword** for your project (called a `slug`, like `bermuda`, `blackholes`, or `ancient_rome`).

### Step 1: Create the Story & Visual Prompts
Tell Matchsticks what topic you want to make a video about:
```bash
python matchsticks.py story bermuda --topic "The Flight 19 mystery in the Bermuda Triangle" --style cinematic
```
* **What happens**: Matchsticks writes a high-retention script, chops it into 2.5-second visual beats, and compiles cinematic prompts into `bermuda/SHOTS.tsv`.
* **5 Visual Styles available**: `cinematic`, `noir`, `anime`, `business`, `hybrid`.

---

### Step 2: Generate Images (Zero Manual Work)
You don't need to craft or paste prompts. Matchsticks generates all images automatically:

```bash
# 🌟 Recommended for Beginners (100% Free, No GPU, No API key needed):
python matchsticks.py generate bermuda --provider web
```

#### Other Image Options:
| Provider | Command | Requirement |
| :--- | :--- | :--- |
| **Free Web** (Default) | `python matchsticks.py generate bermuda --provider web` | Zero setup! Works on any laptop. |
| **Google Gemini / Imagen** | `python matchsticks.py generate bermuda --provider gemini` | Free key from [Google AI Studio](https://aistudio.google.com/). Set `$env:GEMINI_API_KEY="your_key"`. |
| **Local NVIDIA GPU** | `python matchsticks.py generate bermuda --provider local` | Local NVIDIA GPU (SDXL-Turbo, 100% offline). |
| **Manual Art Drop-In** | Drag & drop images into `bermuda/img/clean/s01.jpg`, `s02.jpg`... | Use Midjourney, DALL-E, or Photoshop if you prefer! |

---

### Step 3: Generate Voiceover Narration (Free)
Generate realistic documentary narration with one command:
```bash
# 100% Free Edge-TTS (Broadcast natural documentary narrator):
python matchsticks.py voice bermuda --engine edge

# Or local Kokoro TTS:
python matchsticks.py voice bermuda --engine kokoro
```
*(Have your own voice recording? Just place your audio file as `bermuda/VO.wav`!)*

---

### Step 4: Word Timestamp Alignment
Aligns speech audio with millimeter precision using local Whisper:
```bash
python matchsticks.py ingest bermuda
```
* **What happens**: Detects the exact millisecond each word is spoken, creating `WORDS.tsv` so subtitles sync perfectly.

---

### Step 5: Procedural Sound Design
Adds cinematic whooshes, atmospheric hits, and dynamic speech ducking:
```bash
python matchsticks.py sound bermuda
```
* **What happens**: Mastered audio is saved to `bermuda/mix.wav`.

---

### Step 6: Instant Zero-Render Preview (Browser QC Studio)
Scrub and preview your video with live audio and captions in your web browser **without waiting for video rendering**:
```bash
python matchsticks.py qc bermuda
```
* **What happens**: Opens `qc_player.html` in your browser. Press Play or drag the slider to verify subtitle timing.

---

### Step 7: Render Your Video!

#### 📺 To Render a Full 1080p Master Documentary:
```bash
python matchsticks.py render bermuda --font anton --style minimal
```
* **Your video will be saved at**: `bermuda/exports/bermuda_master_1080p.mp4`

#### 📱 To Render a 9:16 Viral Vertical Short (Opus Clip Style):
```bash
python matchsticks.py short bermuda --mode black --duration 30 --style minimal --title "THE BERMUDA TRIANGLE"
```
* **Your short will be saved at**: `bermuda/exports/bermuda_short_9x16.mp4`
* Preserves the widescreen frame on a pure black background with a top viral curiosity banner and kinetic bottom captions.

---

## ✂️ AI YouTube Auto-Clipper (Opus Clip Alternative)

Turn any existing long YouTube video into viral 9:16 vertical shorts in one command:

```bash
python matchsticks.py clip "https://www.youtube.com/watch?v=..." --duration 30 --font anton --style minimal
```
1. Downloads the YouTube video in high quality.
2. Transcribes spoken words with local Whisper.
3. Formats it into the 9:16 widescreen-on-black canvas.
4. Burns word-synced subtitles and exports the short to `clips/`.

---

## 🎨 Fonts & Caption Styles

### 5 Built-in Fonts:
* `anton` (Impactful, bold documentary font — default)
* `bahnschrift` (Clean modern geometric)
* `impact` (Classic viral style)
* `segoe` (Modern tech explainer)
* `consolas` (Cyber / investigative look)

### 4 Caption Styles:
* `minimal` (Clean 1.5px outline with **zero drop shadow** — modern aesthetic)
* `pill` (High-contrast subtitle background pill)
* `glow` (Atmospheric neon glow highlight)
* `classic` (Traditional television broadcast shadow)

---

## 📁 Clean Project Layout

Every project created by Matchsticks is neatly organized:

```text
projects/<slug>/
├── SCRIPT.md             # The written narrative
├── LINES.tsv             # Timed 2.5s beats
├── SHOTS.tsv             # Image generation prompts
├── STYLE.txt             # Visual mood & palette
│
├── VO.wav                # Spoken narration
├── WORDS.tsv             # Whisper word timestamps
├── mix.wav               # Broadcast audio with SFX ducking
│
├── img/clean/            # Visual scene images (s01.jpg, s02.jpg...)
├── elements/cut/         # Transparent graphic stickers & props
├── qc_player.html        # Interactive browser preview studio
│
└── exports/              # Finished videos
    ├── <slug>_master_1080p.mp4  # 1080p widescreen documentary
    └── <slug>_short_9x16.mp4    # 9:16 vertical viral short
```

---

## ❓ Frequently Asked Questions (Troubleshooting)

**Q: It says `python` is not recognized as an internal or external command.**  
A: Re-run the Python installer, click "Modify", and make sure **"Add Python to PATH"** is checked.

**Q: It says `ffmpeg` is not recognized.**  
A: Install FFmpeg via `winget install Gyan.FFmpeg` on Windows, or restart your terminal after installing.

**Q: Can I use my own images from Midjourney instead of generating them?**  
A: Yes! Simply copy your images into `<project>/img/clean/` as `s01.jpg`, `s02.jpg`, etc. Matchsticks will detect them and skip generation.

**Q: How much does it cost to run?**  
A: **\$0.00**. Using `--provider web` and `--engine edge`, the entire production is 100% free with zero API keys required.

---

## 👨‍💻 Author & Community

* **Created & Developed by**: **Somil Yadav** ([@somil20yadav-debug](https://github.com/somil20yadav-debug))
* **License**: MIT License — open-source, free for personal and commercial use. See [LICENSE](LICENSE) for details.
* **Contributions**: Pull requests, feature ideas, and bug reports are warmly welcome! If you like this project, please consider giving it a ⭐ on GitHub!
