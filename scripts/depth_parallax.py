"""Depth parallax layer decomposition and inpainting engine.
1. Local depth map estimation (Depth Anything V2 Small / MiDaS, with heuristic fallback).
2. 3-layer segmentation (foreground, midground, background) with feathered alpha transitions.
3. Hole filling behind upper layers via LaMa inpainting (with robust cv2.inpaint fallback).
4. Content-addressed layer caching in img/parallax_cache/.
"""
import glob, hashlib, json, os, sys, time, warnings
import cv2
import numpy as np
from PIL import Image, ImageFilter

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
LAMA_MODEL_PATH = os.environ.get("LAMA_MODEL", os.path.join(os.path.expanduser("~"), ".cache", "lama", "big-lama.pt"))

_depth_pipe = None
_depth_load_failed = False
_lama_model = None

def get_depth_pipeline():
    """Lazily initializes the depth estimation pipeline."""
    global _depth_pipe, _depth_load_failed
    if _depth_pipe is not None:
        return _depth_pipe
    if _depth_load_failed:
        return None

    try:
        from transformers import pipeline
        import torch
        device = 0 if torch.cuda.is_available() else -1
        # Try Depth Anything V2 Small first
        try:
            _depth_pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=device)
            return _depth_pipe
        except Exception:
            # Fallback to MiDaS / DPT
            _depth_pipe = pipeline("depth-estimation", model="Intel/dpt-swinv2-tiny-224", device=device)
            return _depth_pipe
    except Exception as e:
        warnings.warn(f"Neural depth pipeline unavailable ({e}). Using local edge/gradient depth estimator.")
        _depth_load_failed = True
        return None

def get_lama_model():
    """Lazily loads the TorchScript LaMa inpainting model if available."""
    global _lama_model
    if _lama_model is not None:
        return _lama_model
    if os.path.exists(LAMA_MODEL_PATH):
        try:
            import torch
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _lama_model = torch.jit.load(LAMA_MODEL_PATH, map_location="cpu").eval()
                return _lama_model
        except Exception:
            return None
    return None

def estimate_depth_map(pil_img):
    """Returns a float32 depth map in [0.0, 1.0] where 1.0=nearest (FG) and 0.0=furthest (BG)."""
    pipe = get_depth_pipeline()
    if pipe is not None:
        try:
            res = pipe(pil_img)
            d_img = res["depth"] if isinstance(res, dict) else res
            d_arr = np.array(d_img.resize(pil_img.size, Image.BILINEAR), dtype=np.float32)
            d_min, d_max = float(d_arr.min()), float(d_arr.max())
            if d_max > d_min:
                d_norm = (d_arr - d_min) / (d_max - d_min)
                return d_norm
        except Exception as e:
            warnings.warn(f"Neural depth estimation failed: {e}. Falling back to visual depth heuristic.")

    # Heuristic depth estimation: combination of vertical atmospheric gradient, saturation, and high-frequency sharpness
    w, h = pil_img.size
    rgb = np.array(pil_img.convert("RGB"), dtype=np.float32)
    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)

    # 1. Perspective y-gradient (things lower in frame are generally closer)
    y_grad = np.linspace(0.1, 0.9, h, dtype=np.float32)[:, None]
    y_grad = np.repeat(y_grad, w, axis=1)

    # 2. Local contrast / detail (foreground has sharper high frequencies)
    blur = cv2.GaussianBlur(gray, (21, 21), 0)
    high_freq = np.abs(gray.astype(np.float32) - blur.astype(np.float32))
    hf_norm = cv2.GaussianBlur(high_freq, (31, 31), 0)
    hf_max = hf_norm.max()
    if hf_max > 0:
        hf_norm /= hf_max

    # 3. Blended depth
    combined = 0.65 * y_grad + 0.35 * hf_norm
    c_min, c_max = combined.min(), combined.max()
    if c_max > c_min:
        combined = (combined - c_min) / (c_max - c_min)
    return combined

def assess_depth_quality(depth_map):
    """Evaluates whether depth map has enough contrast/variation for valid parallax.
    Returns (is_valid, variance, dynamic_range, reason).
    """
    variance = float(np.var(depth_map))
    dyn_range = float(depth_map.max() - depth_map.min())

    if variance < 0.015:
        return False, variance, dyn_range, f"depth variance too low ({variance:.4f} < 0.015)"
    if dyn_range < 0.20:
        return False, variance, dyn_range, f"dynamic range too low ({dyn_range:.3f} < 0.20)"

    return True, variance, dyn_range, "ok"

def inpaint_holes(image_rgb, mask_255):
    """Inpaints holes defined by mask_255 (where 255 = hole to fill).
    Uses LaMa if available; falls back cleanly to OpenCV Telea inpainting.
    """
    if not np.any(mask_255 > 0):
        return image_rgb.copy()

    lama = get_lama_model()
    h, w = image_rgb.shape[:2]

    # Dilate mask slightly to prevent color fringing along boundary
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dilated_mask = cv2.dilate(mask_255, kernel, iterations=2)

    if lama is not None:
        try:
            import torch
            # Run LaMa on full image or crops
            img_t = torch.from_numpy(image_rgb.astype(np.float32) / 255.0).permute(2, 0, 1)[None]
            msk_t = (torch.from_numpy(dilated_mask.astype(np.float32) / 255.0) > 0.5).float()[None, None]
            with torch.no_grad():
                out = lama(img_t, msk_t)[0].permute(1, 2, 0).numpy()
            return np.clip(out * 255.0, 0, 255).astype(np.uint8)
        except Exception:
            pass

    # Robust OpenCV Telea Inpainting fallback
    inpainted = cv2.inpaint(image_rgb, dilated_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
    return inpainted

def split_and_inpaint_layers(pil_img, depth_map):
    """Decomposes the image into 3 layers (FG, MG, BG) with feathered alphas and inpainted backgrounds.
    Returns:
        dict: {
            "fg": PIL.Image (RGBA),
            "mg": PIL.Image (RGBA),
            "bg": PIL.Image (RGB / RGBA)
        }
    """
    w, h = pil_img.size
    rgb = np.array(pil_img.convert("RGB"))

    # Compute depth percentiles for adaptive layer thresholds
    t_bg = float(np.percentile(depth_map, 35))
    t_fg = float(np.percentile(depth_map, 70))
    t_bg = max(0.20, min(0.45, t_bg))
    t_fg = max(t_bg + 0.15, min(0.80, t_fg))

    # Binary masks with smooth transition ramps
    # FG: depth >= t_fg
    fg_raw = np.clip((depth_map - (t_fg - 0.05)) / 0.10, 0.0, 1.0)
    # MG: t_bg <= depth < t_fg
    mg_raw = np.clip((depth_map - (t_bg - 0.05)) / 0.10, 0.0, 1.0) * (1.0 - fg_raw)
    # BG: depth < t_bg
    bg_raw = 1.0 - np.clip((depth_map - (t_bg - 0.05)) / 0.10, 0.0, 1.0)

    # Convert to 8-bit masks
    fg_mask = (fg_raw * 255.0).astype(np.uint8)
    mg_mask = (mg_raw * 255.0).astype(np.uint8)
    bg_mask = (bg_raw * 255.0).astype(np.uint8)

    # Inpaint background behind foreground and midground
    holes_bg = ((fg_mask > 30) | (mg_mask > 30)).astype(np.uint8) * 255
    bg_filled_rgb = inpaint_holes(rgb, holes_bg)

    # Inpaint midground behind foreground
    holes_mg = (fg_mask > 30).astype(np.uint8) * 255
    mg_filled_rgb = inpaint_holes(rgb, holes_mg)

    # Assemble RGBA layers
    fg_rgba = np.dstack([rgb, fg_mask])
    mg_rgba = np.dstack([mg_filled_rgb, mg_mask])
    bg_rgba = np.dstack([bg_filled_rgb, np.full((h, w), 255, dtype=np.uint8)])

    return {
        "fg": Image.fromarray(fg_rgba, "RGBA"),
        "mg": Image.fromarray(mg_rgba, "RGBA"),
        "bg": Image.fromarray(bg_rgba, "RGBA"),
        "thresholds": {"t_bg": round(t_bg, 3), "t_fg": round(t_fg, 3)}
    }

def get_or_create_parallax_layers(img_path, cache_dir=None, force=False):
    """Content-addressed cached retrieval of 3-layer parallax assets.
    Returns (layers_dict, is_cache_hit, quality_info).
    Guarantees watermark removal and full 1920x1080 canvas fit.
    """
    if not os.path.exists(img_path):
        raise FileNotFoundError(f"Image not found: {img_path}")

    # Prioritize watermark-free cleaned image if available
    clean_path = os.path.join(os.path.dirname(img_path), "clean", os.path.splitext(os.path.basename(img_path))[0] + ".png")
    img_to_read = clean_path if os.path.exists(clean_path) else img_path

    with open(img_to_read, "rb") as f:
        img_bytes = f.read()
    img_hash = hashlib.md5(img_bytes).hexdigest()

    if cache_dir is None:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(img_path)), "parallax_cache")
    os.makedirs(cache_dir, exist_ok=True)

    fg_path = os.path.join(cache_dir, f"{img_hash}_fg.png")
    mg_path = os.path.join(cache_dir, f"{img_hash}_mg.png")
    bg_path = os.path.join(cache_dir, f"{img_hash}_bg.png")
    meta_path = os.path.join(cache_dir, f"{img_hash}_meta.json")

    # Check Cache
    if not force and os.path.exists(fg_path) and os.path.exists(mg_path) and os.path.exists(bg_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            layers = {
                "fg": Image.open(fg_path).convert("RGBA"),
                "mg": Image.open(mg_path).convert("RGBA"),
                "bg": Image.open(bg_path).convert("RGBA"),
                "thresholds": meta.get("thresholds", {})
            }
            return layers, True, meta.get("quality", {})
        except Exception:
            pass

    # Compute fresh layers: ensure watermark-free and fitted to full 1920x1080 frame
    sys.path.insert(0, SCRIPTS_DIR)
    from render import W, H, fit, unmark

    raw_img = Image.open(img_to_read).convert("RGB")
    if not os.path.exists(clean_path):
        raw_img = unmark(raw_img)
    pil_img = fit(raw_img)
    depth_map = estimate_depth_map(pil_img)
    is_valid, var, dyn_range, reason = assess_depth_quality(depth_map)

    quality_info = {
        "valid": is_valid,
        "variance": round(var, 5),
        "dynamic_range": round(dyn_range, 4),
        "reason": reason
    }

    layers = split_and_inpaint_layers(pil_img, depth_map)

    # Save to Cache
    layers["fg"].save(fg_path, "PNG")
    layers["mg"].save(mg_path, "PNG")
    layers["bg"].save(bg_path, "PNG")

    meta = {
        "source": os.path.basename(img_path),
        "hash": img_hash,
        "quality": quality_info,
        "thresholds": layers["thresholds"],
        "created_at": time.time()
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return layers, False, quality_info
