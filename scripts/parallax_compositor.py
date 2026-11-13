"""Multi-plane Depth Parallax Compositor.
Applies differential camera motion to Foreground, Midground, and Background layers:
- Speed ratios: Foreground (1.0x), Midground (0.6x), Background (0.25x).
- Moves: push, pull, driftL, driftR, orbit (+-2 deg).
- Zero edge tearing via overscan padding and BORDER_REFLECT on base layer.
- Integrates seamlessly with active camera shake and punch-ins.
"""
import math, os, sys
import cv2
import numpy as np

W, H = 1376, 768

SPEED_RATIOS = {
    "fg": 1.00,
    "mg": 0.60,
    "bg": 0.25
}

def ease_in_out_cubic(p):
    return 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2

def compute_layer_transform(move_type, p, speed_ratio, W, H):
    """Computes affine matrix for a layer under given move_type and progress p in [0, 1]."""
    cx, cy = W / 2.0, H / 2.0
    eased_p = ease_in_out_cubic(max(0.0, min(1.0, p)))

    zoom = 1.0
    shift_x = 0.0
    shift_y = 0.0
    angle_deg = 0.0

    # Max zoom bounds per move
    max_fg_zoom = 0.055

    if move_type == "push":
        # Push-in: FG expands fastest, BG slowest
        z_layer = 1.0 + (max_fg_zoom * speed_ratio) * eased_p
        zoom = z_layer

    elif move_type == "pull":
        # Pull-out: starts zoomed in, eases back out
        z_layer = (1.0 + max_fg_zoom * speed_ratio) - (max_fg_zoom * speed_ratio) * eased_p
        zoom = z_layer

    elif move_type == "driftL":
        # Camera pans right: FG drifts left fastest
        # Base overscan zoom prevents edge leakage
        zoom = 1.025 + (0.015 * speed_ratio)
        max_drift_px = W * 0.012
        shift_x = -max_drift_px * speed_ratio * (eased_p - 0.5)

    elif move_type == "driftR":
        # Camera pans left: FG drifts right fastest
        zoom = 1.025 + (0.015 * speed_ratio)
        max_drift_px = W * 0.012
        shift_x = max_drift_px * speed_ratio * (eased_p - 0.5)

    elif move_type == "orbit":
        # Gentle perspective orbit (+-1.8 deg)
        zoom = 1.035
        max_angle = 1.8 * speed_ratio
        # Orbit rocking curve
        angle_deg = max_angle * math.sin((eased_p - 0.5) * math.pi)
        shift_x = (W * 0.008 * speed_ratio) * math.cos((eased_p - 0.5) * math.pi)

    # Construct Affine Matrix with rotation, scale and translation around center
    rad = math.radians(angle_deg)
    alpha = zoom * math.cos(rad)
    beta = zoom * math.sin(rad)

    tx = (1.0 - alpha) * cx - beta * cy + shift_x
    ty = beta * cx + (1.0 - alpha) * cy + shift_y

    M = np.array([
        [alpha, beta, tx],
        [-beta, alpha, ty]
    ], dtype=np.float32)

    return M

def composite_layers(bg_warped_rgb, mg_warped_rgba, fg_warped_rgba):
    """Blends warped MG and FG onto base BG with anti-aliasing."""
    # Convert BG to float32
    out = bg_warped_rgb.astype(np.float32)

    # Blend Midground
    mg_rgb = mg_warped_rgba[..., :3].astype(np.float32)
    mg_alpha = (mg_warped_rgba[..., 3:4].astype(np.float32)) / 255.0
    out = out * (1.0 - mg_alpha) + mg_rgb * mg_alpha

    # Blend Foreground
    fg_rgb = fg_warped_rgba[..., :3].astype(np.float32)
    fg_alpha = (fg_warped_rgba[..., 3:4].astype(np.float32)) / 255.0
    out = out * (1.0 - fg_alpha) + fg_rgb * fg_alpha

    return np.clip(out, 0, 255).astype(np.uint8)

def render_parallax_frame(layers, move_type, t_in_scene, duration, W, H,
                          active_punch_in=None, active_shake=None, t_master=0.0):
    """Renders a complete parallax composite frame for time t_in_scene.
    layers: dict with 'fg' (RGBA), 'mg' (RGBA), 'bg' (RGB/RGBA)
    """
    if duration <= 0:
        p = 0.0
    else:
        p = max(0.0, min(1.0, t_in_scene / duration))

    # Convert PIL layers to numpy
    fg_np = np.array(layers["fg"]) if hasattr(layers["fg"], "size") else layers["fg"]
    mg_np = np.array(layers["mg"]) if hasattr(layers["mg"], "size") else layers["mg"]
    bg_np = np.array(layers["bg"]) if hasattr(layers["bg"], "size") else layers["bg"]
    if bg_np.shape[2] == 4:
        bg_np = bg_np[..., :3]

    # Strict resolution normalization to (W, H)
    if bg_np.shape[1] != W or bg_np.shape[0] != H:
        bg_np = cv2.resize(bg_np, (W, H), interpolation=cv2.INTER_LANCZOS4)
    if mg_np.shape[1] != W or mg_np.shape[0] != H:
        mg_np = cv2.resize(mg_np, (W, H), interpolation=cv2.INTER_LANCZOS4)
    if fg_np.shape[1] != W or fg_np.shape[0] != H:
        fg_np = cv2.resize(fg_np, (W, H), interpolation=cv2.INTER_LANCZOS4)

    # Calculate affine transform matrices
    M_bg = compute_layer_transform(move_type, p, SPEED_RATIOS["bg"], W, H)
    M_mg = compute_layer_transform(move_type, p, SPEED_RATIOS["mg"], W, H)
    M_fg = compute_layer_transform(move_type, p, SPEED_RATIOS["fg"], W, H)

    # Warp Background with BORDER_REFLECT to guarantee zero border tearing
    bg_warped = cv2.warpAffine(bg_np, M_bg, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

    # Warp Midground and Foreground with transparent border
    mg_warped = cv2.warpAffine(mg_np, M_mg, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    fg_warped = cv2.warpAffine(fg_np, M_fg, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

    # Composite into unified background frame
    composite_rgb = composite_layers(bg_warped, mg_warped, fg_warped)

    # Apply active Punch-In and Camera Shake on the camera frame if active
    from compositor import apply_camera_motion
    has_cam_fx = (active_punch_in is not None) or (active_shake is not None)
    if has_cam_fx:
        composite_rgb = apply_camera_motion(
            composite_rgb, {"type": "static"}, t_in_scene, duration,
            oversample=1.0, active_punch_in=active_punch_in, active_shake=active_shake, t_master=t_master
        )

    return composite_rgb
