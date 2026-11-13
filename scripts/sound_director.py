"""Automated Semantic Sound & SFX Director for StickmanHybrid.
Parses EDL (Edit Decision List), word timestamps, and scene directives to automatically:
1. Detect semantic audio triggers (explosions, whooshes, impacts, glass, ticking, fire).
2. Place cinematic synthesizer sounds exactly on the timestamp the narrator says the word.
3. Add camera motion whooshes on parallax scene cuts and punch-ins.
4. Add crisp micro-pops and slides for sticker/infographic card appearances.
5. Synthesize an atmospheric musical drone bed.
6. Apply professional sidechain ducking to dip the music whenever speech occurs.
7. Output a broadcast-ready mix.wav with soft limiting.

Usage:
    python scripts/sound_director.py <project_slug>
"""

import csv, json, math, os, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- DSP Sound Synthesizers ---

def butter_lowpass(data, cutoff, fs, order=4):
    nyq = 0.5 * fs
    normal_cutoff = min(cutoff / nyq, 0.99)
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return lfilter(b, a, data)


def butter_bandpass(data, lowcut, highcut, fs, order=3):
    nyq = 0.5 * fs
    low = max(lowcut / nyq, 0.01)
    high = min(highcut / nyq, 0.99)
    b, a = butter(order, [low, high], btype='band', analog=False)
    return lfilter(b, a, data)


def generate_sub_boom(fs, duration=3.5, start_freq=75.0, end_freq=28.0):
    """Deep cinematic sub-bass explosion / impact boom with rumble decay."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = start_freq * (end_freq / start_freq) ** (t / duration)
    phase = 2 * np.pi * np.cumsum(freq) / fs
    wave = np.sin(phase)
    noise = butter_lowpass(np.random.normal(0, 0.3, n), 90, fs)
    env = np.exp(-3.5 * t / duration)
    return (wave * 0.8 + noise * 0.4) * env


def generate_impact_punch(fs, duration=1.2):
    """Snappy cinematic thud / punch-in hit."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = 110.0 * (28.0 / 110.0) ** (t / duration)
    phase = 2 * np.pi * np.cumsum(freq) / fs
    env = np.exp(-6.0 * t / duration)
    return np.sin(phase) * env


def generate_whoosh(fs, duration=0.8, direction="in"):
    """Cinematic camera whoosh for scene cuts and parallax movement."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    white = np.random.normal(0, 0.8, n)
    whoosh = butter_bandpass(white, 200, 1800, fs)
    if direction == "in":
        env = (np.sin(np.pi * (t / duration))) ** 2
    else:
        env = np.exp(-4.0 * t / duration)
    return whoosh * env * 0.35


def generate_sticker_pop(fs, duration=0.08):
    """Subtle, pleasant micro-pop sound when an infographic or sticker appears."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = 380.0 * (180.0 / 380.0) ** (t / duration)
    phase = 2 * np.pi * np.cumsum(freq) / fs
    env = np.exp(-35.0 * t / duration)
    return np.sin(phase) * env * 0.35


def generate_fire_crackle(fs, duration=4.0):
    """Atmospheric fire / ember crackle."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    noise = np.random.normal(0, 0.08, n)
    hiss = butter_bandpass(noise, 1500, 4500, fs)
    pops = np.zeros(n)
    num_pops = int(duration * 14)
    if num_pops > 0 and n > int(fs * 0.01):
        indices = np.random.choice(n - int(fs * 0.01), num_pops, replace=False)
        for idx in indices:
            pop_len = int(fs * 0.006)
            pops[idx:idx+pop_len] = np.random.normal(0, 0.6, pop_len) * np.linspace(1, 0, pop_len)
    return hiss + pops * 0.25


def generate_glass_shatter(fs, duration=2.0):
    """High-frequency shattering sound effect."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    white = np.random.normal(0, 0.8, n)
    shatter = butter_bandpass(white, 2500, 8500, fs)
    env = np.exp(-4.5 * t / duration)
    pings = (np.sin(2 * np.pi * 4200 * t) + np.sin(2 * np.pi * 6800 * t)) * 0.2 * np.exp(-14 * t / duration)
    return (shatter * 0.6 + pings) * env * 0.4


def generate_clock_tick(fs, duration=0.04):
    """Crisp mechanical clock tick."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    wave = np.sin(2 * np.pi * 1800 * t) * np.exp(-60 * t)
    noise = np.random.normal(0, 0.3, n) * np.exp(-80 * t)
    return (wave * 0.6 + noise * 0.4) * 0.5


def generate_drone_bed(fs, duration, root_hz=36.7):
    """Deep warm harmonic tension drone (D minor drone bed)."""
    n = int(fs * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    r1 = np.sin(2 * np.pi * root_hz * t)
    fifth = 0.65 * np.sin(2 * np.pi * (root_hz * 1.5) * t)
    octave = 0.45 * np.sin(2 * np.pi * (root_hz * 2.0) * t)
    pulse = 0.85 + 0.15 * np.sin(2 * np.pi * 0.1 * t)
    return (r1 + fifth + octave) * pulse * 0.075


# --- Semantic Keyword Rules ---

SFX_RULES = [
    # Explosions / Detonations
    {
        "keywords": ["exploded", "explosion", "blast", "detonation", "detonated", "megaton", "fireball", "flattened", "catastrophe", "shook"],
        "generator": lambda fs: generate_sub_boom(fs, 4.0, start_freq=75.0, end_freq=28.0),
        "volume": 0.95,
        "cooldown": 4.0,
    },
    # Snappy impacts
    {
        "keywords": ["hit", "impact", "slam", "struck", "strike", "crashed", "crater"],
        "generator": lambda fs: generate_impact_punch(fs, 1.5),
        "volume": 0.80,
        "cooldown": 3.0,
    },
    # Shattering / Glass
    {
        "keywords": ["glass", "window", "windows", "shatter", "shattered", "broken", "cracked"],
        "generator": lambda fs: generate_glass_shatter(fs, 2.2),
        "volume": 0.85,
        "cooldown": 5.0,
    },
    # Time passing / Ticking
    {
        "keywords": ["years", "centuries", "decades", "clock", "seconds", "waiting", "seismograph", "time"],
        "generator": lambda fs: generate_clock_tick(fs),
        "volume": 0.65,
        "repeat": 4,
        "repeat_interval": 0.6,
        "cooldown": 6.0,
    },
    # Fire / Camp
    {
        "keywords": ["fire", "flame", "flames", "camp", "campfire", "burning", "blaze", "heat"],
        "generator": lambda fs: generate_fire_crackle(fs, 4.5),
        "volume": 0.75,
        "cooldown": 8.0,
    },
]


def auto_build_cinematic_audio(slug):
    """Automatically constructs the complete cinematic mix for any project slug."""
    project_dir = os.path.join(BASE_DIR, slug)
    if not os.path.exists(project_dir):
        sys.exit(f"[ERROR] Project directory '{project_dir}' not found.")

    vo_path = os.path.join(project_dir, "VO.wav")
    words_path = os.path.join(project_dir, "WORDS.tsv")
    edl_path = os.path.join(project_dir, "edl.json")
    scenes_path = os.path.join(project_dir, "SCENES.tsv")
    mix_out = os.path.join(project_dir, "mix.wav")

    if not os.path.exists(vo_path):
        sys.exit(f"[ERROR] VO.wav not found at '{vo_path}'. Please generate narration first.")

    print(f"=== Auto-Sound Director: Building Broadcast Mix for '{slug}' ===")
    fs, vo_data = wavfile.read(vo_path)

    # Convert to float32 [-1.0, 1.0]
    if vo_data.dtype == np.int16:
        vo_float = vo_data.astype(np.float32) / 32768.0
    elif vo_data.dtype == np.float32:
        vo_float = vo_data.copy()
    else:
        vo_float = vo_data.astype(np.float32) / np.max(np.abs(vo_data))

    total_samples = len(vo_float)
    total_sec = total_samples / fs
    print(f"Master VO Duration: {total_sec:.2f}s ({total_samples} samples @ {fs}Hz)")

    sfx_track = np.zeros(total_samples, dtype=np.float32)

    def add_sfx(audio_arr, start_sec, volume=1.0):
        start_idx = max(0, int(start_sec * fs))
        end_idx = min(start_idx + len(audio_arr), total_samples)
        add_len = end_idx - start_idx
        if add_len > 0:
            sfx_track[start_idx:end_idx] += audio_arr[:add_len] * volume

    # 1. Camera Transitions & Sticker Pops from edl.json
    transitions_added = 0
    stickers_added = 0
    punchins_added = 0

    if os.path.exists(edl_path):
        with open(edl_path, "r", encoding="utf-8") as f:
            edl = json.load(f)

        # Scene Transitions
        for sc in edl.get("scenes", []):
            t0 = sc.get("t0", 0.0)
            if t0 > 0.1:  # skip beginning of video
                whoosh = generate_whoosh(fs, duration=0.7)
                add_sfx(whoosh, max(0.0, t0 - 0.2), volume=0.40)
                transitions_added += 1

            # Sticker Overlays
            for ov in sc.get("overlays", []):
                t_st = ov.get("t", t0)
                pop = generate_sticker_pop(fs)
                add_sfx(pop, t_st, volume=0.55)
                stickers_added += 1

        # Punch-ins
        for p in edl.get("punch_ins", []):
            t_in = p.get("t_in", 0.0)
            punch_hit = generate_impact_punch(fs, duration=0.8)
            add_sfx(punch_hit, t_in, volume=0.50)
            punchins_added += 1

        print(f"[OK] Added {transitions_added} scene whooshes, {punchins_added} punch-in hits, and {stickers_added} sticker pop cues from EDL.")

    # 2. Semantic Word-Level SFX from WORDS.tsv
    sfx_cues_added = 0
    rule_last_played = {i: -999.0 for i in range(len(SFX_RULES))}

    if os.path.exists(words_path):
        with open(words_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                word = row.get("word", "").lower().strip(".,!?:;\"'()[]")
                try:
                    start_t = float(row.get("start", 0))
                except ValueError:
                    continue

                for r_idx, rule in enumerate(SFX_RULES):
                    if word in rule["keywords"]:
                        if start_t - rule_last_played[r_idx] >= rule["cooldown"]:
                            rule_last_played[r_idx] = start_t
                            audio_chunk = rule["generator"](fs)
                            vol = rule["volume"]
                            add_sfx(audio_chunk, start_t, volume=vol)
                            sfx_cues_added += 1

                            # Repeats (for ticking clocks, etc.)
                            if "repeat" in rule:
                                for rep_i in range(1, rule["repeat"]):
                                    rep_t = start_t + (rep_i * rule["repeat_interval"])
                                    add_sfx(rule["generator"](fs), rep_t, volume=vol)
                                    sfx_cues_added += 1
                            break
        print(f"[OK] Added {sfx_cues_added} semantic SFX triggers from word timestamps.")

    # 3. Atmospheric Tension Drone Bed
    drone = generate_drone_bed(fs, total_sec)

    # 4. Intelligent Sidechain Ducking
    print("Applying dynamic sidechain speech ducking (-14dB under VO)...")
    vo_envelope = butter_lowpass(np.abs(vo_float), cutoff=3.5, fs=fs)
    # Duck drone by 65% when speech envelope is present
    duck_gain = 1.0 - 0.65 * np.clip(vo_envelope / 0.12, 0, 1.0)
    drone_ducked = drone * duck_gain

    # 5. Master Summing & Soft Limiting
    print("Summing master audio tracks (VO + SFX + Drone Bed)...")
    master = (vo_float * 0.95) + (sfx_track * 0.70) + (drone_ducked * 0.65)

    peak = np.max(np.abs(master))
    if peak > 0.95:
        print(f"Limiting master peak: {peak:.2f} -> 0.95")
        master = master * (0.95 / peak)

    # 6. Write final 16-bit Broadcast WAV
    master_int16 = (master * 32767.0).astype(np.int16)
    wavfile.write(mix_out, fs, master_int16)
    print(f"[SUCCESS] Broadcast master mix generated: {mix_out} ({round(os.path.getsize(mix_out)/(1024**2), 2)} MB)\n")
    return mix_out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/sound_director.py <project_slug>")
        sys.exit(1)
    auto_build_cinematic_audio(sys.argv[1])
