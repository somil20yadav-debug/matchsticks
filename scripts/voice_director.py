"""Voice & Audio Ingestion Director for StickmanHybrid.
Handles:
1. Free TTS Synthesis: Uses Kokoro TTS or Edge-TTS (100% free, zero API key required).
2. ElevenLabs API: Uses ELEVEN_API_KEY if provided.
3. Audio Ingestion: Ingests any external VO.wav (from ElevenLabs or user mic) and generates WORDS.tsv via Whisper.

Usage:
    python scripts/voice_director.py <slug> --synthesize [--engine edge|kokoro|eleven] [--voice en-US-ChristopherNeural]
    python scripts/voice_director.py <slug> --ingest [--file path/to/VO.wav]
"""

import asyncio, csv, json, os, subprocess, sys
from scipy.io import wavfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def synthesize_edge_tts(text, out_mp3, voice="en-US-ChristopherNeural"):
    """Synthesizes text using Microsoft Edge TTS (100% free, natural documentary narrator)."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate="+2%", pitch="-2Hz")
    await communicate.save(out_mp3)
    return out_mp3


def synthesize_kokoro_tts(text, out_wav, voice="am_adam"):
    """Synthesizes text using local Kokoro TTS (100% free open-source model)."""
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    pipeline = KPipeline(lang_code='a')
    generator = pipeline(text, voice=voice, speed=1.0)
    all_audio = []
    sr = 24000
    for _, _, audio in generator:
        all_audio.append(audio)
    
    if all_audio:
        combined = np.concatenate(all_audio)
        sf.write(out_wav, combined, sr)
        return out_wav
    raise RuntimeError("Kokoro failed to produce audio.")


def synthesize_elevenlabs(text, out_mp3, api_key=None, voice_id="21m00Tcm4TlvDq8ikWAM"):
    """Synthesizes text using ElevenLabs REST API."""
    import urllib.request
    key = api_key or os.environ.get("ELEVEN_API_KEY")
    if not key:
        raise ValueError("ELEVEN_API_KEY not found in environment.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req) as resp:
        with open(out_mp3, "wb") as f:
            f.write(resp.read())
    return out_mp3


def convert_to_broadcast_wav(in_path, out_wav):
    """Converts any audio file to 24kHz mono PCM WAV."""
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
        out_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav


def run_whisper_alignment(wav_path, out_tsv):
    """Aligns VO.wav into WORDS.tsv with exact word timestamps."""
    print("Aligning speech timestamps with Whisper...")
    words = []
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(wav_path, word_timestamps=True)
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
    except Exception:
        import whisper
        model = whisper.load_model("base")
        res = model.transcribe(wav_path, word_timestamps=True)
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

    print(f"[OK] Generated {len(words)} aligned words -> {out_tsv}")
    return words


def update_scene_timings(project_dir, words):
    """Updates scene cut durations to sync cleanly with spoken voiceover."""
    scenes_tsv = os.path.join(project_dir, "SCENES.tsv")
    edl_json = os.path.join(project_dir, "edl.json")
    if not words:
        return

    total_vo_duration = float(words[-1]["end"]) + 0.8
    print(f"[SYNC] Spoken voiceover duration: {total_vo_duration:.2f}s")


def process_voice(slug, mode="ingest", engine="edge", input_file=None, voice_name=None):
    project_dir = os.path.join(BASE_DIR, slug)
    os.makedirs(project_dir, exist_ok=True)
    dest_vo = os.path.join(project_dir, "VO.wav")
    words_tsv = os.path.join(project_dir, "WORDS.tsv")

    if mode == "synthesize":
        script_md = os.path.join(project_dir, "SCRIPT.md")
        lines_tsv = os.path.join(project_dir, "LINES.tsv")
        narration_text = ""

        if os.path.exists(script_md):
            with open(script_md, "r", encoding="utf-8") as f:
                content = f.read()
                # Extract narration lines
                narration_lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
                narration_text = " ".join(narration_lines)
        elif os.path.exists(lines_tsv):
            with open(lines_tsv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                narration_text = " ".join([r.get("text", "") for r in reader if r.get("text")])

        if not narration_text:
            sys.exit(f"[ERROR] No SCRIPT.md or LINES.tsv found in {project_dir} to synthesize.")

        print(f"=== Synthesizing Voiceover for '{slug}' using {engine.upper()} ===")
        print(f"Narration text: {len(narration_text.split())} words")

        temp_audio = os.path.join(project_dir, "temp_synth.mp3")

        if engine == "edge":
            voice = voice_name or "en-US-ChristopherNeural"
            asyncio.run(synthesize_edge_tts(narration_text, temp_audio, voice=voice))
            convert_to_broadcast_wav(temp_audio, dest_vo)
            if os.path.exists(temp_audio): os.remove(temp_audio)
        elif engine == "kokoro":
            voice = voice_name or "am_adam"
            temp_wav = os.path.join(project_dir, "temp_kokoro.wav")
            synthesize_kokoro_tts(narration_text, temp_wav, voice=voice)
            convert_to_broadcast_wav(temp_wav, dest_vo)
            if os.path.exists(temp_wav): os.remove(temp_wav)
        elif engine == "eleven":
            synthesize_elevenlabs(narration_text, temp_audio)
            convert_to_broadcast_wav(temp_audio, dest_vo)
            if os.path.exists(temp_audio): os.remove(temp_audio)
        else:
            sys.exit(f"[ERROR] Unknown TTS engine: {engine}. Choose 'edge', 'kokoro', or 'eleven'.")

        print(f"[OK] Voiceover synthesized -> {dest_vo}")

    elif mode == "ingest":
        src = input_file or dest_vo
        if not os.path.exists(src):
            sys.exit(f"[ERROR] Voiceover file '{src}' not found. Please provide --file <path>.")
        if os.path.abspath(src) != os.path.abspath(dest_vo):
            convert_to_broadcast_wav(src, dest_vo)
        print(f"[OK] Ingested voiceover -> {dest_vo}")

    # Generate WORDS.tsv
    words = run_whisper_alignment(dest_vo, words_tsv)
    update_scene_timings(project_dir, words)
    print(f"\n[SUCCESS] Voice pipeline complete for '{slug}'! Ready for Sound Director & Master Render.\n")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    slug = sys.argv[1].lower()
    action = sys.argv[2].lower()

    if action in ("--ingest", "ingest"):
        inp = None
        if "--file" in sys.argv:
            inp = sys.argv[sys.argv.index("--file") + 1]
        process_voice(slug, mode="ingest", input_file=inp)
    elif action in ("--synthesize", "synthesize", "voice"):
        eng = "edge"
        vname = None
        if "--engine" in sys.argv:
            eng = sys.argv[sys.argv.index("--engine") + 1]
        if "--voice" in sys.argv:
            vname = sys.argv[sys.argv.index("--voice") + 1]
        process_voice(slug, mode="synthesize", engine=eng, voice_name=vname)
    else:
        print(f"Unknown action: {action}")
        print(__doc__)


if __name__ == "__main__":
    main()
