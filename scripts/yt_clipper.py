"""AI YouTube & Video Auto-Clipper (Opus Clip Alternative) for StickmanHybrid.
Downloads YouTube videos (or takes local MP4), extracts word timestamps via Whisper,
applies smart 9:16 subject pan-and-scan, and renders kinetic subtitles.

Usage:
    python scripts/yt_clipper.py <youtube_url_or_file> [--start 0.0] [--duration 30.0] [--font bahnschrift] [--style minimal] [--name my_clip]
"""

import csv, json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")
sys.path.append(SCRIPTS_DIR)

from caption_renderer import CaptionEngine, resolve_font


def download_youtube(url, dest_dir):
    """Downloads YouTube video via yt-dlp."""
    os.makedirs(dest_dir, exist_ok=True)
    out_template = os.path.join(dest_dir, "source.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_template,
        url
    ]
    print(f"Downloading YouTube video -> {dest_dir}...")
    subprocess.run(cmd, check=True)
    
    target_mp4 = os.path.join(dest_dir, "source.mp4")
    if not os.path.exists(target_mp4):
        # find downloaded mp4
        for f in os.listdir(dest_dir):
            if f.endswith(".mp4"):
                return os.path.join(dest_dir, f)
    return target_mp4


def extract_audio(video_path, out_wav):
    """Extracts 24kHz mono WAV for Whisper."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
        out_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav


def transcribe_words(wav_path, out_tsv):
    """Transcribes audio using faster-whisper or openai-whisper to produce WORDS.tsv."""
    print("Transcribing audio with word timestamps (Whisper)...")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(wav_path, word_timestamps=True)
        
        words = []
        w_idx = 0
        for seg in segments:
            for w in seg.words:
                words.append({
                    "line": str(seg.id),
                    "i": str(w_idx),
                    "start": f"{w.start:.3f}",
                    "end": f"{w.end:.3f}",
                    "word": w.word.strip()
                })
                w_idx += 1
    except Exception as e:
        print(f"[WARN] faster-whisper fallback: {e}")
        import whisper
        model = whisper.load_model("base")
        res = model.transcribe(wav_path, word_timestamps=True)
        words = []
        w_idx = 0
        for s_idx, seg in enumerate(res.get("segments", [])):
            for w in seg.get("words", []):
                words.append({
                    "line": str(s_idx),
                    "i": str(w_idx),
                    "start": f"{w['start']:.3f}",
                    "end": f"{w['end']:.3f}",
                    "word": w["word"].strip()
                })
                w_idx += 1

    with open(out_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["line", "i", "start", "end", "word"], delimiter="\t")
        writer.writeheader()
        writer.writerows(words)
    print(f"[OK] Generated word timestamps: {len(words)} words -> {out_tsv}")
    return out_tsv


def auto_clip(video_source, start_t=0.0, duration=30.0, font="bahnschrift", style="minimal", name=None):
    """Clips video to 9:16 vertical with smart crop and kinetic subtitles."""
    os.makedirs(CLIPS_DIR, exist_ok=True)
    
    # Check if video_source is URL or local file
    if video_source.startswith("http://") or video_source.startswith("https://"):
        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', video_source.split("=")[-1] if "=" in video_source else "yt_clip")[:16]
        work_dir = os.path.join(CLIPS_DIR, slug)
        video_path = download_youtube(video_source, work_dir)
    else:
        video_path = os.path.abspath(video_source)
        slug = os.path.splitext(os.path.basename(video_path))[0]
        work_dir = os.path.join(CLIPS_DIR, slug)
        os.makedirs(work_dir, exist_ok=True)

    clip_name = name or f"{slug}_clip"
    out_mp4 = os.path.join(work_dir, f"{clip_name}.mp4")
    wav_path = os.path.join(work_dir, "audio.wav")
    words_tsv = os.path.join(work_dir, "WORDS.tsv")

    if not os.path.exists(wav_path):
        extract_audio(video_path, wav_path)
    if not os.path.exists(words_tsv):
        transcribe_words(wav_path, words_tsv)

    # Slice video segment to 1080x1920 (9:16 center/smart crop)
    # Using FFmpeg filter: scale to height 1920, then crop 1080:1920
    sliced_video = os.path.join(work_dir, "temp_slice.mp4")
    crop_filter = "scale=-1:1920,crop=1080:1920:(in_w-1080)/2:0"
    
    print(f"Extracting 9:16 vertical slice ({start_t}s - {start_t + duration}s)...")
    cmd_slice = [
        "ffmpeg", "-y",
        "-ss", str(start_t),
        "-t", str(duration),
        "-i", video_path,
        "-vf", crop_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        sliced_video
    ]
    subprocess.run(cmd_slice, check=True)

    # Initialize caption engine
    cap_engine = CaptionEngine(words_tsv, font_name=font, style=style, font_size=56, W=1080, H=1920)

    # Extract frames, overlay captions, re-encode
    frames_dir = os.path.join(work_dir, "temp_frames")
    os.makedirs(frames_dir, exist_ok=True)

    print("Extracting frames for kinetic caption overlay...")
    cmd_extract = [
        "ffmpeg", "-y", "-i", sliced_video,
        "-q:v", "2",
        os.path.join(frames_dir, "frame_%05d.jpg")
    ]
    subprocess.run(cmd_extract, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_files = sorted(os.listdir(frames_dir))
    fps = len(frame_files) / duration
    print(f"Applying '{font}' ({style}) captions to {len(frame_files)} frames @ {fps:.1f} fps...")

    for idx, fname in enumerate(frame_files):
        fpath = os.path.join(frames_dir, fname)
        t_current = start_t + (idx / fps)
        im = Image.open(fpath)
        im = cap_engine.render_caption_on_image(im, t_current, y_pos=1480)
        im.save(fpath, quality=92)

    # Extract sliced audio
    sliced_audio = os.path.join(work_dir, "temp_slice_audio.wav")
    subprocess.run(["ffmpeg", "-y", "-i", sliced_video, "-vn", "-acodec", "pcm_s16le", sliced_audio],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Stitch final 9:16 short
    print(f"Stitching final viral short -> {out_mp4}...")
    cmd_stitch = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%05d.jpg"),
        "-i", sliced_audio,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        out_mp4
    ]
    subprocess.run(cmd_stitch, check=True)

    # Clean up frames
    try:
        import shutil
        shutil.rmtree(frames_dir)
        if os.path.exists(sliced_video): os.remove(sliced_video)
        if os.path.exists(sliced_audio): os.remove(sliced_audio)
    except Exception:
        pass

    print(f"\n[SUCCESS] AI Short clipped: {out_mp4}")
    return out_mp4


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    source = sys.argv[1]
    start_t = 0.0
    duration = 30.0
    font = "bahnschrift"
    style = "minimal"
    name = None

    if "--start" in sys.argv:
        start_t = float(sys.argv[sys.argv.index("--start") + 1])
    if "--duration" in sys.argv:
        duration = float(sys.argv[sys.argv.index("--duration") + 1])
    if "--font" in sys.argv:
        font = sys.argv[sys.argv.index("--font") + 1]
    if "--style" in sys.argv:
        style = sys.argv[sys.argv.index("--style") + 1]
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]

    out = auto_clip(source, start_t=start_t, duration=duration, font=font, style=style, name=name)
    try:
        subprocess.run(["cmd", "/c", "start", "", out])
    except Exception:
        pass


if __name__ == "__main__":
    main()
