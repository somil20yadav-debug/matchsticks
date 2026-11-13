"""Procedural generator and renderer for Stickman Mascot Peeks.
Provides the 4 approved poses: curious, shocked, thinking, pointing.
Supports corners: bl (bottom-left), br (bottom-right), left-edge.
Includes white die-cut sticker border and soft shadow.
"""
import math, os
from PIL import Image, ImageDraw, ImageFilter

POSES = ("curious", "shocked", "thinking", "pointing")
CORNERS = ("bl", "br", "left-edge")

_mascot_cache = {}

def draw_mascot(pose="curious", corner="bl", size=500):
    """Generates an RGBA PIL Image of the stickman mascot in the requested pose and corner."""
    key = (pose, corner, size)
    if key in _mascot_cache:
        return _mascot_cache[key].copy()

    # Draw at 2x resolution for clean anti-aliasing
    S = 2
    canvas_size = size * S
    im = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    ink = (32, 28, 32, 255)
    body_fill = (248, 246, 242, 255)
    mouth_fill = (40, 36, 40, 255)
    line_w = int(10 * S)

    # Base coordinates (anchored near bottom center of canvas)
    cx = canvas_size // 2
    head_cy = int(canvas_size * 0.38)
    head_r = int(canvas_size * 0.18)

    # Pose specific adjustments
    tilt = 0
    if pose == "curious":
        tilt = 12
    elif pose == "thinking":
        tilt = -8

    # Neck and chest
    neck_top = head_cy + head_r - int(8 * S)
    chest_y = neck_top + int(canvas_size * 0.18)
    hip_y = canvas_size - int(10 * S)

    # Draw torso
    draw.line((cx, neck_top, cx, hip_y), fill=ink, width=line_w)

    # Draw arms based on pose
    if pose == "curious":
        # Left arm resting on bezel/edge, right arm slightly raised
        draw.line((cx, chest_y, cx - int(head_r * 1.3), chest_y + int(30 * S)), fill=ink, width=line_w)
        draw.line((cx - int(head_r * 1.3), chest_y + int(30 * S), cx - int(head_r * 1.7), hip_y - int(20 * S)), fill=ink, width=line_w)
        draw.line((cx, chest_y, cx + int(head_r * 1.1), chest_y + int(20 * S)), fill=ink, width=line_w)
        draw.line((cx + int(head_r * 1.1), chest_y + int(20 * S), cx + int(head_r * 1.5), hip_y - int(10 * S)), fill=ink, width=line_w)
    elif pose == "shocked":
        # Both hands clutching head / raised in alarm
        draw.line((cx, chest_y, cx - int(head_r * 1.4), head_cy + int(10 * S)), fill=ink, width=line_w)
        draw.line((cx - int(head_r * 1.4), head_cy + int(10 * S), cx - int(head_r * 1.1), head_cy - int(10 * S)), fill=ink, width=line_w)
        draw.line((cx, chest_y, cx + int(head_r * 1.4), head_cy + int(10 * S)), fill=ink, width=line_w)
        draw.line((cx + int(head_r * 1.4), head_cy + int(10 * S), cx + int(head_r * 1.1), head_cy - int(10 * S)), fill=ink, width=line_w)
    elif pose == "thinking":
        # One hand on chin, one arm folded across chest
        # Left arm folded across
        draw.line((cx, chest_y + int(10 * S), cx - int(head_r * 0.9), chest_y + int(35 * S)), fill=ink, width=line_w)
        draw.line((cx - int(head_r * 0.9), chest_y + int(35 * S), cx + int(head_r * 0.3), chest_y + int(25 * S)), fill=ink, width=line_w)
        # Right arm up to chin
        draw.line((cx, chest_y, cx + int(head_r * 0.9), chest_y + int(15 * S)), fill=ink, width=line_w)
        draw.line((cx + int(head_r * 0.9), chest_y + int(15 * S), cx + int(head_r * 0.2), head_cy + head_r - int(10 * S)), fill=ink, width=line_w)
        # Hand on chin
        draw.ellipse((cx + int(head_r * 0.15), head_cy + head_r - int(18 * S), cx + int(head_r * 0.35), head_cy + head_r - int(2 * S)), fill=body_fill, outline=ink, width=int(5 * S))
    elif pose == "pointing":
        # One arm pointing across towards scene, other arm down
        pointing_dir = -1 if corner == "br" else 1
        px_target = cx + pointing_dir * int(head_r * 2.1)
        py_target = chest_y - int(15 * S)
        draw.line((cx, chest_y, cx + pointing_dir * int(head_r * 1.1), chest_y - int(10 * S)), fill=ink, width=line_w)
        draw.line((cx + pointing_dir * int(head_r * 1.1), chest_y - int(10 * S), px_target, py_target), fill=ink, width=line_w)
        # Pointing hand finger
        draw.line((px_target, py_target, px_target + pointing_dir * int(25 * S), py_target - int(5 * S)), fill=ink, width=int(7 * S))
        # Other arm resting
        draw.line((cx, chest_y, cx - pointing_dir * int(head_r * 0.9), chest_y + int(30 * S)), fill=ink, width=line_w)
        draw.line((cx - pointing_dir * int(head_r * 0.9), chest_y + int(30 * S), cx - pointing_dir * int(head_r * 1.3), hip_y - int(20 * S)), fill=ink, width=line_w)

    # Draw Head with fill and outline
    hx0, hy0 = cx - head_r, head_cy - head_r
    hx1, hy1 = cx + head_r, head_cy + head_r
    draw.ellipse((hx0, hy0, hx1, hy1), fill=body_fill, outline=ink, width=line_w)

    # Draw Eyes & Facial Expression
    eye_r = int(12 * S)
    pupil_r = int(6 * S)
    if pose == "curious":
        # Big curious eyes looking slightly to the side
        lex, ley = cx - int(head_r * 0.35), head_cy - int(head_r * 0.05)
        rex, rey = cx + int(head_r * 0.35), head_cy - int(head_r * 0.05)
        draw.ellipse((lex - eye_r, ley - eye_r, lex + eye_r, ley + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((rex - eye_r, rey - eye_r, rex + eye_r, rey + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((lex, ley - pupil_r, lex + 2 * pupil_r, ley + pupil_r), fill=ink)
        draw.ellipse((rex, rey - pupil_r, rex + 2 * pupil_r, rey + pupil_r), fill=ink)
        # Gentle smile
        draw.arc((cx - int(head_r * 0.3), head_cy + int(head_r * 0.1), cx + int(head_r * 0.3), head_cy + int(head_r * 0.5)), 20, 160, fill=ink, width=int(5 * S))
    elif pose == "shocked":
        # Wide round open eyes
        s_eye_r = int(16 * S)
        lex, ley = cx - int(head_r * 0.38), head_cy - int(head_r * 0.15)
        rex, rey = cx + int(head_r * 0.38), head_cy - int(head_r * 0.15)
        draw.ellipse((lex - s_eye_r, ley - s_eye_r, lex + s_eye_r, ley + s_eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((rex - s_eye_r, rey - s_eye_r, rex + s_eye_r, rey + s_eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((lex - int(3*S), ley - int(3*S), lex + int(3*S), ley + int(3*S)), fill=ink)
        draw.ellipse((rex - int(3*S), rey - int(3*S), rex + int(3*S), rey + int(3*S)), fill=ink)
        # O-mouth
        draw.ellipse((cx - int(head_r * 0.22), head_cy + int(head_r * 0.2), cx + int(head_r * 0.22), head_cy + int(head_r * 0.65)), fill=mouth_fill, outline=ink, width=int(4 * S))
    elif pose == "thinking":
        # Eyes looking up and thinking eyebrow
        lex, ley = cx - int(head_r * 0.35), head_cy - int(head_r * 0.1)
        rex, rey = cx + int(head_r * 0.35), head_cy - int(head_r * 0.1)
        draw.ellipse((lex - eye_r, ley - eye_r, lex + eye_r, ley + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((rex - eye_r, rey - eye_r, rex + eye_r, rey + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((lex - pupil_r, ley - eye_r + int(2*S), lex + pupil_r, ley - eye_r + int(2*S) + 2*pupil_r), fill=ink)
        draw.ellipse((rex - pupil_r, rey - eye_r + int(2*S), rex + pupil_r, rey - eye_r + int(2*S) + 2*pupil_r), fill=ink)
        # Thinking mouth (wavy line)
        draw.line((cx - int(head_r * 0.25), head_cy + int(head_r * 0.35), cx + int(head_r * 0.25), head_cy + int(head_r * 0.32)), fill=ink, width=int(4 * S))
    elif pose == "pointing":
        # Confident alert eyes looking forward
        pointing_dir = -1 if corner == "br" else 1
        lex, ley = cx - int(head_r * 0.35), head_cy - int(head_r * 0.05)
        rex, rey = cx + int(head_r * 0.35), head_cy - int(head_r * 0.05)
        draw.ellipse((lex - eye_r, ley - eye_r, lex + eye_r, ley + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        draw.ellipse((rex - eye_r, rey - eye_r, rex + eye_r, rey + eye_r), fill=body_fill, outline=ink, width=int(4 * S))
        offset_x = pointing_dir * int(4 * S)
        draw.ellipse((lex + offset_x - pupil_r, ley - pupil_r, lex + offset_x + pupil_r, ley + pupil_r), fill=ink)
        draw.ellipse((rex + offset_x - pupil_r, rey - pupil_r, rex + offset_x + pupil_r, rey + pupil_r), fill=ink)
        # Confident smirk
        draw.arc((cx - int(head_r * 0.2), head_cy + int(head_r * 0.15), cx + int(head_r * 0.35), head_cy + int(head_r * 0.45)), 10, 150, fill=ink, width=int(5 * S))

    # Downscale for crisp antialiasing
    rendered = im.resize((size, size), Image.LANCZOS)

    # Apply White Die-Cut Sticker Border + Soft Paper Shadow
    b = max(6, size // 38)
    pad = b * 3
    big = Image.new("RGBA", (rendered.width + 2 * pad, rendered.height + 2 * pad), (0, 0, 0, 0))
    big.paste(rendered, (pad, pad), rendered)

    ring = big.getchannel("A").filter(ImageFilter.MaxFilter(2 * b + 1))
    shadow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    shadow.putalpha(ring.point(lambda v: int(v * 0.38)).filter(ImageFilter.GaussianBlur(b * 1.4)))

    white = Image.new("RGBA", big.size, (255, 255, 255, 0))
    white.putalpha(ring)

    final_mascot = Image.new("RGBA", big.size, (0, 0, 0, 0))
    final_mascot.alpha_composite(shadow, (b // 2, b))
    final_mascot.alpha_composite(white)
    final_mascot.alpha_composite(big)

    # Trim empty padding along bounding box
    bbox = final_mascot.getbbox()
    if bbox:
        final_mascot = final_mascot.crop(bbox)

    _mascot_cache[key] = final_mascot
    return final_mascot.copy()

def get_mascot_image(pose="curious", corner="bl", target_h=340):
    """Returns the ready-to-composite sticker mascot cropped and scaled to target height."""
    im = draw_mascot(pose=pose, corner=corner, size=int(target_h * 1.2))
    aspect = im.width / im.height
    w = max(1, int(target_h * aspect))
    return im.resize((w, target_h), Image.LANCZOS)
