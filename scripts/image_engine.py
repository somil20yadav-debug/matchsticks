"""Universal Image Generation Engine for Matchsticks.
Supports tiered providers so anyone can run it 100% free on their laptop,
use free Google Gemini/Imagen keys, run local offline GPUs, or scale to Google Flow.

Providers:
- 'web' / 'free-web': 100% free, zero-key, zero-setup public generator (Pollinations / Public SD).
- 'gemini' / 'imagen': Official Google AI Studio API (via GEMINI_API_KEY).
- 'local' / 'local-diffusers': High-performance local GPU generation via PyTorch & Diffusers (CUDA/MPS).
- 'flow': Google Flow connector bridge (flow-auto).
- 'mock': Offline gradient placeholders for instant pipeline & parallax testing without internet.
"""

import base64, csv, json, os, sys, time, urllib.parse, requests
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def generate_image(prompt, output_path, provider="auto", width=1920, height=1080, ref_image=None):
    """Dispatches prompt to the appropriate generation backend."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if provider == "auto":
        try:
            from hardware import get_hardware_profile
            hw = get_hardware_profile()
            provider = hw.get("recommended_image_provider", "free-web")
        except Exception:
            provider = "free-web"

    p = provider.lower().strip()

    if p in ("mock", "placeholder"):
        return _generate_mock(prompt, output_path, width, height)
    elif p in ("gemini", "imagen"):
        return _generate_gemini(prompt, output_path, width, height)
    elif p in ("local", "local-diffusers", "diffusers", "gpu"):
        try:
            return _generate_local_diffusers(prompt, output_path, width, height)
        except Exception as e:
            print(f"[WARN] Local diffusers failed ({e}). Falling back to free-web provider...")
            return _generate_free_web(prompt, output_path, width, height)
    elif p == "flow":
        return _generate_flow(prompt, output_path, ref_image)
    else:  # 'web', 'free-web', 'pollinations' default
        return _generate_free_web(prompt, output_path, width, height)


def _generate_mock(prompt, output_path, width, height):
    """Instant offline placeholder generator with cinematic gradient & prompt overlay."""
    im = Image.new("RGB", (width, height), (20, 24, 38))
    draw = ImageDraw.Draw(im)

    for y in range(height):
        factor = y / height
        r = int(25 + factor * 40)
        g = int(30 + factor * 20)
        b = int(45 + factor * 10)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    label = f"[Matchsticks Offline Mock]\n{prompt[:100]}..."
    draw.text((width // 10, height // 2 - 20), label, fill=(240, 240, 240))
    im.save(output_path, quality=95)
    return output_path


def _generate_free_web(prompt, output_path, width, height):
    """Zero-key, 100% free web generation endpoint using Pollinations.ai."""
    clean_prompt = prompt.replace("\n", " ").strip()
    encoded = urllib.parse.quote(clean_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&seed={int(time.time() * 1000) % 99999}"

    print(f"  [WEB GEN] Fetching: {clean_prompt[:65]}...")
    headers = {"User-Agent": "Matchsticks/1.0"}
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path
    else:
        raise RuntimeError(f"Free web provider returned status code {resp.status_code}")


def _generate_gemini(prompt, output_path, width, height):
    """Google Imagen generation using free-tier GEMINI_API_KEY from Google AI Studio."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[WARN] GEMINI_API_KEY not set in environment. Falling back to free-web provider...")
        return _generate_free_web(prompt, output_path, width, height)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={api_key}"
    aspect = "16:9" if width >= height else "9:16"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": aspect}
    }
    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code == 200:
        data = resp.json()
        b64_img = data["predictions"][0]["bytesBase64Encoded"]
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64_img))
        return output_path
    else:
        print(f"[WARN] Gemini Imagen API returned {resp.status_code}: {resp.text[:100]}. Falling back to free-web...")
        return _generate_free_web(prompt, output_path, width, height)


def _generate_local_diffusers(prompt, output_path, width, height):
    """Local GPU generation using PyTorch and Hugging Face Diffusers."""
    import torch
    from diffusers import AutoPipelineForText2Image

    device = "cuda" if torch.cuda.is_available() else ("mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu")
    torch_dtype = torch.float16 if device == "cuda" else torch.float32

    pipeline = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch_dtype,
        variant="fp16" if device == "cuda" else None,
    )
    pipeline.to(device)

    image = pipeline(prompt=prompt, num_inference_steps=2, guidance_scale=0.0, width=width, height=height).images[0]
    image.save(output_path)
    return output_path


def _generate_flow(prompt, output_path, ref_image=None):
    """Google Flow generation via flow-auto CLI."""
    import subprocess, shutil
    flow_cmd = shutil.which("flow-auto") or shutil.which("flow-auto.cmd") or os.path.expandvars(r"%APPDATA%\npm\flow-auto.CMD")
    if not flow_cmd or not os.path.exists(flow_cmd):
        raise FileNotFoundError("Google Flow CLI ('flow-auto') not found in PATH.")

    cmd = [flow_cmd, "generate", "create", "flow-text-to-image", "--prompt", prompt]
    if ref_image and os.path.exists(ref_image):
        cmd[3] = "flow-image-to-image"
        cmd.extend(["--image", ref_image])

    subprocess.run(cmd, check=True)
    return output_path


def batch_generate_project(slug, provider="auto", force=False):
    """Reads SHOTS.tsv and automatically generates all missing scene images."""
    project_dir = os.path.join(BASE_DIR, slug)
    shots_path = os.path.join(project_dir, "SHOTS.tsv")
    clean_dir = os.path.join(project_dir, "img", "clean")
    os.makedirs(clean_dir, exist_ok=True)

    if not os.path.exists(shots_path):
        raise FileNotFoundError(f"SHOTS.tsv not found at {shots_path}. Run 'python matchsticks.py story {slug}' first.")

    shots = []
    with open(shots_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            shots.append(r)

    print(f"\n=======================================================")
    print(f" MATCHSTICKS IMAGE ENGINE: {slug.upper()}")
    print(f" Provider: {provider.upper()} | Total Shots: {len(shots)}")
    print(f" Destination: {clean_dir}")
    print(f"=======================================================")

    success_count = 0
    skipped_count = 0

    for idx, s in enumerate(shots, 1):
        shot_id = int(s.get("id", idx))
        prompt = s.get("prompt", "")
        out_jpg = os.path.join(clean_dir, f"s{shot_id:02d}.jpg")
        out_png = os.path.join(clean_dir, f"s{shot_id:02d}.png")

        if not force and (os.path.exists(out_jpg) or os.path.exists(out_png)):
            print(f"  [{shot_id:02d}/{len(shots):02d}] Already exists -> Skipping.")
            skipped_count += 1
            continue

        target_file = out_jpg
        try:
            generate_image(prompt, target_file, provider=provider, width=1920, height=1080)
            print(f"  [{shot_id:02d}/{len(shots):02d}] Done -> s{shot_id:02d}.jpg")
            success_count += 1
            time.sleep(0.5)  # Graceful rate limit pacing
        except Exception as e:
            print(f"  [{shot_id:02d}/{len(shots):02d}] FAILED: {e}")

    print(f"\n[COMPLETE] Generated: {success_count} | Skipped: {skipped_count} | Total: {len(shots)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/image_engine.py <slug> [--provider auto|web|gemini|local|mock] [--force]")
        sys.exit(1)

    slug = sys.argv[1].lower()
    provider = "auto"
    force = "--force" in sys.argv

    if "--provider" in sys.argv:
        provider = sys.argv[sys.argv.index("--provider") + 1]

    batch_generate_project(slug, provider=provider, force=force)


if __name__ == "__main__":
    main()
