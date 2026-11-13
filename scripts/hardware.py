"""Hardware & Tier Auto-Detector for StickmanHybrid.
Inspects the user's system (CUDA GPU, Apple Silicon MPS, or CPU) and assigns
the optimal generation profile so the tool runs smoothly on any laptop or workstation.
"""

import os, sys, platform


def get_hardware_profile():
    """Detects available hardware accelerators, VRAM, and assigns a performance tier."""
    profile = {
        "os": platform.system(),
        "arch": platform.machine(),
        "device": "cpu",
        "device_name": platform.processor() or "CPU",
        "vram_gb": 0.0,
        "tier": 1,
        "tier_name": "Tier 1: Lightweight Laptop / CPU Mode",
        "recommended_resolution": (1280, 720),
        "recommended_fps": 30,
        "recommended_image_provider": "free-web",  # zero-cost, zero-key fallback
        "recommended_depth_model": "lightweight-cpu",
    }

    try:
        import torch

        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            total_vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(total_vram_bytes / (1024**3), 2)

            profile["device"] = "cuda"
            profile["device_name"] = device_name
            profile["vram_gb"] = vram_gb

            if vram_gb >= 11.5:
                # High-End Desktop GPU (RTX 3080/3090/4070/4080/4090)
                profile["tier"] = 3
                profile["tier_name"] = "Tier 3: Enthusiast GPU Mode (Flux / High-Res Parallax)"
                profile["recommended_resolution"] = (1920, 1080)
                profile["recommended_fps"] = 60
                profile["recommended_image_provider"] = "local-diffusers"
                profile["recommended_depth_model"] = "depth-anything-v2-large"
            elif vram_gb >= 5.5:
                # Mid-Range GPU (RTX 3060, 4050, 4060, 2060, 8GB laptop GPUs)
                profile["tier"] = 2
                profile["tier_name"] = "Tier 2: Mid-Range GPU Mode (SDXL Turbo / 1080p Parallax)"
                profile["recommended_resolution"] = (1920, 1080)
                profile["recommended_fps"] = 30
                profile["recommended_image_provider"] = "local-diffusers"
                profile["recommended_depth_model"] = "depth-anything-v2-small"
            else:
                # Entry-level GPU (4GB GTX 1650, etc.)
                profile["tier"] = 1.5
                profile["tier_name"] = "Tier 1.5: Entry GPU Mode (SD 1.5 / Low-VRAM)"
                profile["recommended_resolution"] = (1280, 720)
                profile["recommended_fps"] = 30
                profile["recommended_image_provider"] = "free-web"
                profile["recommended_depth_model"] = "midas-small"

        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # Apple Silicon Mac (M1/M2/M3/M4)
            profile["device"] = "mps"
            profile["device_name"] = "Apple Silicon GPU (Metal)"
            profile["tier"] = 2
            profile["tier_name"] = "Tier 2: Apple Silicon Metal Mode"
            profile["recommended_resolution"] = (1920, 1080)
            profile["recommended_fps"] = 30
            profile["recommended_image_provider"] = "local-diffusers"
            profile["recommended_depth_model"] = "depth-anything-v2-small"

    except Exception:
        pass

    return profile


def print_hardware_summary():
    p = get_hardware_profile()
    print("=" * 60)
    print("  StickmanHybrid: Hardware & Acceleration Profile")
    print("=" * 60)
    print(f"  OS / Architecture:      {p['os']} ({p['arch']})")
    print(f"  Compute Device:         {p['device'].upper()} ({p['device_name']})")
    if p["vram_gb"] > 0:
        print(f"  Dedicated VRAM:         {p['vram_gb']} GB")
    print(f"  Active Tier:            {p['tier_name']}")
    print(f"  Target Resolution:      {p['recommended_resolution'][0]}x{p['recommended_resolution'][1]} @ {p['recommended_fps']} fps")
    print(f"  Default Image Engine:   {p['recommended_image_provider']}")
    print(f"  Default Depth Engine:   {p['recommended_depth_model']}")
    print("=" * 60)
    return p


if __name__ == "__main__":
    print_hardware_summary()
