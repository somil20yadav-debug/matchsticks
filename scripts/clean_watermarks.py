"""Surgical Gemini Watermark Removal for Flow Generations (StickmanHybrid).
Removes ONLY the 18x18px Gemini 4-point sparkle diamond at (339, 469) [relative to 382x512].
Zero blurred square artifacts, zero destruction of artwork.

Usage:
    python scripts/clean_watermarks.py <slug_or_path>
    python scripts/clean_watermarks.py dark_forest/part1
"""

import os
import sys
import glob
import cv2
import numpy as np
from project_resolver import resolve_project_dir

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def clean_image_surgical(in_path, out_path):
    orig = cv2.imread(in_path)
    if orig is None:
        print(f"[ERROR] Could not load {in_path}")
        return False

    h, w, _ = orig.shape

    # Exact surgical 4-point diamond mask for Google Flow's Gemini sparkle on 382x512
    # Sparkle is centered at x=339, y=469 (inset ~34px from right and bottom edges)
    # Scale proportionally if resolution differs
    scale_x = w / 382.0
    scale_y = h / 512.0

    cx = int(339 * scale_x)
    cy = int(469 * scale_y)
    rad_x = int(12 * scale_x)
    rad_y = int(12 * scale_y)

    mask = np.zeros((h, w), dtype=np.uint8)
    pts = np.array([
        [cx, cy - rad_y],
        [cx + rad_x, cy],
        [cx, cy + rad_y],
        [cx - rad_x, cy]
    ], np.int32)

    cv2.fillPoly(mask, [pts], 255)
    # Expand slightly by 1 pixel to guarantee seamless edge coverage
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    # Inpaint only the diamond pixels using Telea method (smooth texture continuation)
    clean = cv2.inpaint(orig, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, clean)
    return True


def clean_directory(target_path):
    # Resolve target directory
    proj_dir = resolve_project_dir(target_path)

    if not os.path.exists(proj_dir):
        print(f"[ERROR] Directory does not exist: {proj_dir}")
        return

    # Check if this is an img directory directly or a project directory containing img/
    if os.path.exists(os.path.join(proj_dir, "img")):
        img_dir = os.path.join(proj_dir, "img")
    else:
        img_dir = proj_dir

    clean_dir = os.path.join(img_dir, "clean")
    os.makedirs(clean_dir, exist_ok=True)

    input_files = sorted(
        glob.glob(os.path.join(img_dir, "*.webp")) +
        glob.glob(os.path.join(img_dir, "*.png")) +
        glob.glob(os.path.join(img_dir, "*.jpg"))
    )
    # Exclude files inside clean/
    input_files = [f for f in input_files if os.path.dirname(f) != clean_dir]

    print(f"=== SURGICAL WATERMARK REMOVAL ===")
    print(f"Target: {img_dir}")
    print(f"Found {len(input_files)} source images to clean...")

    cleaned_count = 0
    for f in input_files:
        base_name = os.path.splitext(os.path.basename(f))[0]
        out_png = os.path.join(clean_dir, f"{base_name}.png")
        if clean_image_surgical(f, out_png):
            cleaned_count += 1
            print(f"  [CLEAN] {os.path.basename(f)} -> {base_name}.png (sparkle erased)")

    print(f"\n[DONE] {cleaned_count}/{len(input_files)} images cleaned surgically without blur boxes.\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/clean_watermarks.py <slug_or_directory>")
        sys.exit(1)

    target = sys.argv[1]
    clean_directory(target)


if __name__ == "__main__":
    main()
