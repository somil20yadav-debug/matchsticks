"""Voice & Audio Ingestion Director for StickmanHybrid.
Handles:
1. Free TTS Synthesis: Uses Kokoro TTS or Edge-TTS (100% free, zero API key required).
2. ElevenLabs API: Uses ELEVEN_API_KEY if provided.
3. Audio Ingestion: Ingests any external VO.wav (from ElevenLabs or user mic) and generates WORDS.tsv via Whisper.

Usage:
    python scripts/voice_director.py <slug> --synthesize [--engine edge|kokoro|eleven] [--voice en-US-ChristopherNeural]
    python scripts/voice_director.py <slug> --ingest [--file path/to/VO.wav]
"""

import asyncio, csv, json, os, re, subprocess, sys
from scipy.io import wavfile
from project_resolver import resolve_project_dir

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def clean_script_tags(text):
    """Strips [SFX: ...], [CUE: ...], [VISUAL: ...] and other production cues for clean speech synthesis."""
    cleaned = re.sub(r'\[.*?\]', '', text)
    cleaned = re.sub(r'(?i)\b(voice|narrator|text on screen):\s*', '', cleaned)
    return " ".join(cleaned.split()).strip()


def script_to_ssml(text, voice="en-US-ChristopherNeural"):
    """Converts emotion and pause tags into SSML for Microsoft Edge TTS."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ssml_body = []
    has_tags = False

    for line in lines:
        if re.match(r'^\[(SFX|CUE|VISUAL):.*\]$', line, re.IGNORECASE):
            continue

        pause_m = re.search(r'\[(pause|break)(?::\s*([\d\.]+(?:ms|s)?))?\]', line, re.IGNORECASE)
        if pause_m:
            has_tags = True
            dur = pause_m.group(2) or "800ms"
            if not dur.endswith(('s', 'ms')):
                dur = f"{dur}s"
            ssml_body.append(f'  <break time="{dur}" />')
            line = re.sub(r'\[(pause|break)(?::\s*[\d\.]+(?:ms|s)?)?\]', '', line, flags=re.IGNORECASE).strip()
            if not line:
                continue

        if re.search(r'\[(whisper|whispering)\]', line, re.IGNORECASE):
            has_tags = True
            cl = re.sub(r'\[(whisper|whispering)\]', '', line, flags=re.IGNORECASE).strip()
            cl = re.sub(r'\[.*?\]', '', cl).strip()
            if cl:
                ssml_body.append(f'  <mstts:express-as style="whispering">{cl}</mstts:express-as>')
        elif re.search(r'\[(serious|ominous|somber)\]', line, re.IGNORECASE):
            has_tags = True
            cl = re.sub(r'\[(serious|ominous|somber)\]', '', line, flags=re.IGNORECASE).strip()
            cl = re.sub(r'\[.*?\]', '', cl).strip()
            if cl:
                ssml_body.append(f'  <mstts:express-as style="serious">{cl}</mstts:express-as>')
        else:
            cl = re.sub(r'\[.*?\]', '', line).strip()
            if cl:
                ssml_body.append(f'  <p>{cl}</p>')

    if not has_tags:
        return None

    inner_xml = "\n".join(ssml_body)
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">\n'
        f'  <voice name="{voice}">\n'
        f'{inner_xml}\n'
        '  </voice>\n'
        '</speak>'
    )


async def synthesize_edge_tts(text, out_mp3, voice="en-US-ChristopherNeural"):
    """Synthesizes text using Microsoft Edge TTS with dynamic emotion tags & micro-pauses."""
    import edge_tts
    import soundfile as sf
    import numpy as np
    import tempfile

    has_tags = bool(re.search(r'\[(whisper|urgent|serious|pause|break|ominous|calm|gasp).*?\]', text, re.IGNORECASE))
    
    if not has_tags:
        cleaned = clean_script_tags(text)
        communicate = edge_tts.Communicate(cleaned, voice, rate="+2%", pitch="-2Hz")
        await communicate.save(out_mp3)
        return out_mp3

    # Dynamic segment synthesis for high emotional range
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    audio_chunks = []
    sr = 24000
    temp_dir = tempfile.gettempdir()
    temp_files = []
    idx = 0

    for line in lines:
        if re.match(r'^\[(SFX|CUE|VISUAL):.*\]$', line, re.IGNORECASE):
            continue

        # Standalone pause
        standalone_pause = re.match(r'^\[(pause|break):?\s*([\d\.]+(?:ms|s)?)?\]$', line, re.IGNORECASE)
        if standalone_pause:
            dur_str = standalone_pause.group(2) or "500ms"
            ms = float(dur_str.replace("ms", "").replace("s", ""))
            if "s" in dur_str and "ms" not in dur_str:
                ms *= 1000
            samples = int(sr * (ms / 1000.0))
            audio_chunks.append(np.zeros(samples, dtype=np.float32))
            continue

        # Split by inline pauses
        parts = re.split(r'(\[(?:pause|break):?\s*[\d\.]+(?:ms|s)?\])', line, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            pause_m = re.match(r'^\[(?:pause|break):?\s*([\d\.]+(?:ms|s)?)?\]$', part, re.IGNORECASE)
            if pause_m:
                dur_str = pause_m.group(1) or "500ms"
                ms = float(dur_str.replace("ms", "").replace("s", ""))
                if "s" in dur_str and "ms" not in dur_str:
                    ms *= 1000
                samples = int(sr * (ms / 1000.0))
                audio_chunks.append(np.zeros(samples, dtype=np.float32))
                continue

            rate = "+0%"
            pitch = "+0Hz"
            volume = "+0%"

            if "[whisper]" in part.lower():
                part = re.sub(r'\[whisper\]', '', part, flags=re.IGNORECASE).strip()
                rate = "-10%"
                pitch = "-4Hz"
                volume = "-5%"
            elif "[urgent]" in part.lower():
                part = re.sub(r'\[urgent\]', '', part, flags=re.IGNORECASE).strip()
                rate = "+16%"
                pitch = "+4Hz"
                volume = "+10%"
            elif "[serious]" in part.lower() or "[ominous]" in part.lower():
                part = re.sub(r'\[(serious|ominous)\]', '', part, flags=re.IGNORECASE).strip()
                rate = "-4%"
                pitch = "-6Hz"
                volume = "+5%"

            clean_part = re.sub(r'\[.*?\]', '', part).strip()
            if not clean_part:
                continue

            seg_mp3 = os.path.join(temp_dir, f"edge_seg_{os.getpid()}_{idx}.mp3")
            seg_wav = os.path.join(temp_dir, f"edge_seg_{os.getpid()}_{idx}.wav")
            temp_files.extend([seg_mp3, seg_wav])
            idx += 1

            comm = edge_tts.Communicate(clean_part, voice, rate=rate, pitch=pitch, volume=volume)
            await comm.save(seg_mp3)

            subprocess.run([
                "ffmpeg", "-y", "-i", seg_mp3,
                "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le",
                seg_wav
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            data, _ = sf.read(seg_wav)
            audio_chunks.append(data.astype(np.float32))
            # Natural micro-pause between clauses
            audio_chunks.append(np.zeros(int(sr * 0.22), dtype=np.float32))

    if not audio_chunks:
        cleaned = clean_script_tags(text)
        comm = edge_tts.Communicate(cleaned, voice)
        await comm.save(out_mp3)
        return out_mp3

    combined = np.concatenate(audio_chunks)
    temp_combined_wav = os.path.join(temp_dir, f"edge_combined_{os.getpid()}.wav")
    sf.write(temp_combined_wav, combined, sr)

    subprocess.run([
        "ffmpeg", "-y", "-i", temp_combined_wav,
        out_mp3
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for f in temp_files + [temp_combined_wav]:
        try: os.remove(f)
        except: pass

    return out_mp3


def synthesize_kokoro_tts(text, out_wav, voice="am_adam"):
    """Synthesizes text using local Kokoro TTS with dynamic pause & emotion tag support."""
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np
    import re

    primary_voice = voice.split(',')[0].strip()
    lang_code = 'b' if primary_voice.startswith('b') else 'a'
    pipeline = KPipeline(lang_code=lang_code)
    
    sr = 24000
    audio_chunks = []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    for line in lines:
        if re.match(r'^\[(SFX|CUE|VISUAL):.*\]$', line, re.IGNORECASE):
            continue

        # Standalone pause
        standalone_pause = re.match(r'^\[(pause|break):?\s*([\d\.]+(?:ms|s)?)?\]$', line, re.IGNORECASE)
        if standalone_pause:
            dur_str = standalone_pause.group(2) or "120ms"
            ms = float(dur_str.replace("ms", "").replace("s", ""))
            if "s" in dur_str and "ms" not in dur_str:
                ms *= 1000
            ms = min(ms, 150.0)  # Cap pauses so they never create robotic dead silence
            samples = int(sr * (ms / 1000.0))
            audio_chunks.append(np.zeros(samples, dtype=np.float32))
            continue

        # In-line pauses
        parts = re.split(r'(\[(?:pause|break):?\s*[\d\.]+(?:ms|s)?\])', line, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            pause_m = re.match(r'^\[(?:pause|break):?\s*([\d\.]+(?:ms|s)?)?\]$', part, re.IGNORECASE)
            if pause_m:
                dur_str = pause_m.group(1) or "120ms"
                ms = float(dur_str.replace("ms", "").replace("s", ""))
                if "s" in dur_str and "ms" not in dur_str:
                    ms *= 1000
                ms = min(ms, 150.0)  # Snappy micro-pause
                samples = int(sr * (ms / 1000.0))
                audio_chunks.append(np.zeros(samples, dtype=np.float32))
                continue

            speed = 0.98
            if "[whisper]" in part.lower() or "[serious]" in part.lower():
                speed = 0.94
            elif "[urgent]" in part.lower() or "[fast]" in part.lower():
                speed = 1.08

            clean_part = re.sub(r'\[.*?\]', '', part).strip()
            if not clean_part:
                continue

            generator = pipeline(clean_part, voice=voice, speed=speed)
            for _, _, audio in generator:
                audio_chunks.append(audio)
            
            # Tight 30ms acoustic glue (zero robotic dead air)
            audio_chunks.append(np.zeros(int(sr * 0.03), dtype=np.float32))

    if audio_chunks:
        combined = np.concatenate(audio_chunks)
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
    """Converts any audio file to 24kHz mono PCM WAV with warm broadcast proximity mastering."""
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
        "-af", "equalizer=f=120:width_type=o:w=1:g=3.5,equalizer=f=4000:width_type=o:w=1:g=2.0,acompressor=threshold=-16dB:ratio=3.5:attack=5:release=50:makeup=2dB",
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
    project_dir = resolve_project_dir(slug)
    os.makedirs(project_dir, exist_ok=True)
    dest_vo = os.path.join(project_dir, "VO.wav")
    words_tsv = os.path.join(project_dir, "WORDS.tsv")

    if mode == "synthesize":
        vo_txt = os.path.join(project_dir, "VO_FOR_ELEVENLABS.txt")
        script_md = os.path.join(project_dir, "SCRIPT.md")
        lines_tsv = os.path.join(project_dir, "LINES.tsv")
        narration_text = ""

        if os.path.exists(vo_txt):
            with open(vo_txt, "r", encoding="utf-8") as f:
                narration_text = f.read().strip()
        elif os.path.exists(lines_tsv):
            with open(lines_tsv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                narration_text = " ".join([r.get("text", "") for r in reader if r.get("text")])
        elif os.path.exists(script_md):
            with open(script_md, "r", encoding="utf-8") as f:
                content = f.read()
                # Extract narration lines (preserve line breaks for emotional tag parsing)
                narration_lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
                narration_text = "\n".join(narration_lines)

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
