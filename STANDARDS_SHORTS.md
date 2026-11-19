# Vertical Shorts & Reels Visual Standard (3:4 Prestige Editorial)

> **Mandate Approved by Ashoka-10 Council (Rulings: 94/100 & 92/100)**  
> **Effective Date:** November 19, 2026  
> **Applies to:** ALL YouTube Shorts, Instagram Reels, and TikTok Vertical Video Production.

---

## 1. Core Canvas Architecture (1080 x 1920 px)

All vertical content is rendered on a $1080 \times 1920$ black canvas (`#000000`) utilizing the **3:4 Portrait Aspect Ratio**:

```
+-----------------------------------------------------------+ (0, 0)
|                                                           |
|  UPPER LETTERBOX [240px]: Prestige Editorial Header       |
|  - Pill Badge: Cyan (#58a6ff), Bahnschrift 24px          |
|  - Hook Headline: Bold White (#FFFFFF), Anton 56px        |
|                                                           |
+-----------------------------------------------------------+ (0, 240)
|                                                           |
|                                                           |
|             ACTIVE 3:4 COMIC NOIR ARTWORK                 |
|                   (1080 x 1440 px)                        |
|                                                           |
|             * 75% Total Screen Coverage *                 |
|             * ZERO Horizontal Crop Loss *                 |
|             * Exact Stickman & Space Preservation *       |
|                                                           |
|                                                           |
+-----------------------------------------------------------+ (0, 1680)
|                                                           |
|  LOWER LETTERBOX [240px]: Word-Synced Subtitles          |
|  - Active Word: Yellow (#FFD02A), Anton 58px              |
|  - Spoken Words: Pure White (#FFFFFF)                     |
|  - Position: y = 1740 (Clear of YouTube Shorts UI)        |
|                                                           |
+-----------------------------------------------------------+ (1080, 1920)
```

---

## 2. Watermark Removal Policy (Zero Tolerance for Blurred Boxes)

1. **Detection:** Google Flow generations output an $18 \times 18\text{ px}$ 4-point Gemini diamond sparkle located at `(339, 469)` (proportional to $382 \times 512$).
2. **Strict Prohibition:** Do NOT use blanket box delogo or square blur filters (e.g. standard `flow-auto clean` 58x58 box), which destroy the artwork and create ugly blurred boxes.
3. **Surgical Inpainting:**
   - Execute:
     ```powershell
     python scripts/clean_watermarks.py <project_slug>
     ```
   - Uses `cv2.INPAINT_TELEA` on the exact 4-point polygon mask with a 1-pixel dilation.
   - `shorts_builder.py` auto-detects and surgically cleans raw WebP images on the fly if uncleaned.

---

## 3. Character & Visual Style Standard

- **Character Policy:** Pure minimalist 2D black stickman.
- **Strictly Prohibited:** Zero BOMA mascots, no red scarves, no cartoon hats, no 3D shading.
- **Lighting & Atmosphere:** High-contrast graphic novel noir, volumetric rim lighting, deep space blues, moody shadows, and cinematic scale.

---

## 4. Single-Command Production Commands

### A. Watermark Cleaning:
```powershell
python scripts/clean_watermarks.py dark_forest/part1
```

### B. Rendering a Standard Short:
```powershell
python scripts/shorts_builder.py dark_forest/part1 --badge "🌌 THE DARK FOREST // EPISODE 1" --title "WHY THE UNIVERSE IS SILENT"
```

The output master will automatically be saved to:
`<slug>/exports/<slug>_master.mp4`
