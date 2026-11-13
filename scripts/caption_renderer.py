"""Universal Multi-Style & Multi-Font Kinetic Caption Engine for StickmanHybrid.
Supports 5 distinct documentary fonts and 4 customizable visual styles.

5 Available Fonts:
- 'anton': Bold, punchy condensed (Vox / MagnatesMedia standard)
- 'bahnschrift': Clean geometric DIN (Military / Scientific / Historical standard)
- 'impact': Heavyweight viral punch (High-CTR social standard)
- 'segoe': Ultra-clean modern sans (Apple / BBC / Minimalist documentary)
- 'consolas': Classified typewriter monospace (Historical archives & dossiers)

4 Caption Styles:
- 'minimal': Zero drop-shadow, ultra-clean thin outline (modern aesthetic)
- 'pill': Translucent rounded dark glassmorphic badge behind the words
- 'glow': Soft ambient neon glow around active words, zero black shadow
- 'classic': High-contrast bold outline with tight drop shadow
"""

import csv, os, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

FONT_REGISTRY = {
    "anton": os.path.join(FONTS_DIR, "Anton-Regular.ttf"),
    "bahnschrift": r"C:\Windows\Fonts\bahnschrift.ttf",
    "impact": r"C:\Windows\Fonts\impact.ttf",
    "segoe": r"C:\Windows\Fonts\segoeuib.ttf",
    "consolas": r"C:\Windows\Fonts\consolab.ttf",
}


def resolve_font(font_name, size):
    """Resolves one of the 5 studio fonts or falls back cleanly."""
    font_key = font_name.lower().strip()
    target_path = FONT_REGISTRY.get(font_key)

    if target_path and os.path.exists(target_path):
        try:
            return ImageFont.truetype(target_path, size)
        except Exception:
            pass

    # Fallback search
    for p in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeui.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class CaptionEngine:
    def __init__(self, words_tsv_path, font_name="anton", style="minimal", font_size=52, W=1920, H=1080):
        self.W = W
        self.H = H
        self.font_size = font_size
        self.font_name = font_name.lower()
        self.style = style.lower()  # 'minimal', 'pill', 'glow', 'classic'

        self.font_active_size = int(font_size * 1.14)
        self.font = resolve_font(self.font_name, self.font_size)
        self.font_active = resolve_font(self.font_name, self.font_active_size)

        # Space measurement (minimum 38% of font size for clean visual breathing room)
        font_space = int(self.font.getlength(" ")) if hasattr(self.font, "getlength") else int(self.font_size * 0.35)
        self.space_w = max(font_space, int(self.font_size * 0.38))

        self.chunks = []
        self._load_words(words_tsv_path)

    def _is_number_or_date(self, text):
        clean = text.strip(".,!?;:\"'")
        return bool(re.search(r'\d', clean)) or clean.lower() in ("million", "billion", "thousand", "centuries", "years")

    def _load_words(self, words_tsv_path):
        if not os.path.exists(words_tsv_path):
            return

        words = []
        with open(words_tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for r in reader:
                try:
                    words.append({
                        "line": r.get("line", ""),
                        "word": r.get("word", ""),
                        "start": float(r.get("start", 0.0)),
                        "end": float(r.get("end", 0.0)),
                        "i": int(r.get("i", 0))
                    })
                except ValueError:
                    continue

        cur_words = []
        for w in words:
            cur_words.append(w)
            txt = w["word"]
            ends_sentence = txt.endswith((".", "?", "!"))
            ends_clause = txt.endswith((",", ";", ":"))
            if len(cur_words) >= 4 or (len(cur_words) >= 2 and ends_clause) or ends_sentence:
                self._add_chunk(cur_words)
                cur_words = []
        if cur_words:
            self._add_chunk(cur_words)

    def _add_chunk(self, words_list):
        if not words_list:
            return
        
        word_items = []
        total_w = 0
        max_h = 0
        for w in words_list:
            raw_text = w["word"].rstrip(".,!?;:\"'")
            disp_word = raw_text.lower() if self.font_name != "consolas" else raw_text
            bbox = self.font.getbbox(disp_word)
            ww = bbox[2] - bbox[0]
            wh = bbox[3] - bbox[1]
            word_items.append({
                "text": disp_word,
                "start": w["start"],
                "end": w["end"],
                "width": ww,
                "height": wh,
                "is_num": self._is_number_or_date(disp_word)
            })
            total_w += ww
            if wh > max_h:
                max_h = wh
        
        total_w += self.space_w * (len(word_items) - 1)
        start_t = words_list[0]["start"]
        end_t = words_list[-1]["end"]
        
        self.chunks.append({
            "start": start_t,
            "end": end_t,
            "words": word_items,
            "total_w": total_w,
            "max_h": max_h
        })

    def get_active_chunk(self, t):
        for c in self.chunks:
            if c["start"] <= t <= c["end"] + 0.12:
                return c
        return None

    def render_caption_on_image(self, pil_img, t, y_pos=None):
        chunk = self.get_active_chunk(t)
        if chunk is None:
            return pil_img

        cx = self.W // 2
        cy = y_pos if y_pos is not None else (self.H - 110)
        max_h = chunk["max_h"]

        # Dynamic layout resolution at time t
        # Measures exact active vs inactive font glyph advances so words never collide or overlap
        rendered_words = []
        total_w = 0
        space_w = max(int(self.font.getlength(" ")) if hasattr(self.font, "getlength") else int(self.font_size * 0.35),
                      int(self.font_size * 0.38))

        for w in chunk["words"]:
            is_active = (w["start"] <= t <= w["end"])
            f = self.font_active if is_active else self.font
            adv_w = f.getlength(w["text"]) if hasattr(f, "getlength") else (f.getbbox(w["text"])[2] - f.getbbox(w["text"])[0])
            rendered_words.append({
                "text": w["text"],
                "is_active": is_active,
                "is_num": w["is_num"],
                "font": f,
                "adv_w": adv_w
            })
            total_w += adv_w

        total_w += space_w * (len(rendered_words) - 1)

        # Auto-Shrink Font Guard: Prevents long phrases or scientific words from clipping screen edges
        max_allowed_w = int(self.W * 0.86)
        if total_w > max_allowed_w and total_w > 0:
            scale_factor = max_allowed_w / total_w
            space_w = max(8, int(space_w * scale_factor))
            for rw in rendered_words:
                cur_sz = self.font_active_size if rw["is_active"] else self.font_size
                rw["font"] = resolve_font(self.font_name, max(24, int(cur_sz * scale_factor)))
                rw["adv_w"] = rw["font"].getlength(rw["text"]) if hasattr(rw["font"], "getlength") else rw["adv_w"] * scale_factor
            total_w = sum(rw["adv_w"] for rw in rendered_words) + space_w * (len(rendered_words) - 1)

        start_x = cx - int(total_w) // 2

        if pil_img.mode != "RGBA" and self.style in ("pill", "glow"):
            pil_img = pil_img.convert("RGBA")
        elif pil_img.mode != "RGB" and self.style not in ("pill", "glow"):
            pil_img = pil_img.convert("RGB")

        # -------------------------------------------------------------
        # STYLE 1: PILL (Vox / Kurzgesagt Glassmorphic Badge)
        # -------------------------------------------------------------
        if self.style == "pill":
            pad_x = 24
            pad_y = 12
            pill_w = int(total_w) + pad_x * 2
            pill_h = max_h + pad_y * 2
            pill_x0 = cx - pill_w // 2
            pill_y0 = cy - pill_h // 2

            pill_overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            p_draw = ImageDraw.Draw(pill_overlay)
            p_draw.rounded_rectangle([(pill_x0, pill_y0), (pill_x0 + pill_w, pill_y0 + pill_h)],
                                     radius=12, fill=(10, 14, 22, 185), outline=(60, 70, 90, 220), width=1)
            pil_img = Image.alpha_composite(pil_img, pill_overlay)
            draw = ImageDraw.Draw(pil_img)

            cur_x = start_x
            for rw in rendered_words:
                col = "#FFD02A" if rw["is_active"] else ("#00F0FF" if rw["is_num"] else "#FFFFFF")
                y_offset = (cy - max_h // 2) - (2 if rw["is_active"] else 0)

                draw.text((cur_x, y_offset), rw["text"], font=rw["font"], fill=col)
                cur_x += rw["adv_w"] + space_w
            return pil_img.convert("RGB")

        # -------------------------------------------------------------
        # STYLE 2: PURE GLOW (Soft Ambient Light, Zero Black Shadows)
        # -------------------------------------------------------------
        elif self.style == "glow":
            glow_overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            g_draw = ImageDraw.Draw(glow_overlay)

            cur_x = start_x
            for rw in rendered_words:
                if rw["is_active"]:
                    y_offset = (cy - max_h // 2) - 3
                    g_draw.text((cur_x, y_offset), rw["text"], font=rw["font"], fill=(255, 208, 42, 160), stroke_width=8, stroke_fill=(255, 180, 0, 100))
                cur_x += rw["adv_w"] + space_w

            glow_blurred = glow_overlay.filter(ImageFilter.GaussianBlur(radius=6))
            pil_img = Image.alpha_composite(pil_img, glow_blurred)
            draw = ImageDraw.Draw(pil_img)

            cur_x = start_x
            for rw in rendered_words:
                col = "#FFD02A" if rw["is_active"] else ("#00F0FF" if rw["is_num"] else "#FFFFFF")
                y_offset = (cy - max_h // 2) - (3 if rw["is_active"] else 0)

                draw.text((cur_x, y_offset), rw["text"], font=rw["font"], fill=col, stroke_width=2, stroke_fill=(20, 20, 20, 220))
                cur_x += rw["adv_w"] + space_w
            return pil_img.convert("RGB")

        # -------------------------------------------------------------
        # STYLE 3: MINIMAL (Pure Clean Text, Thin 1.5px Outline, NO SHADOW)
        # -------------------------------------------------------------
        elif self.style == "minimal":
            draw = ImageDraw.Draw(pil_img)
            cur_x = start_x
            for rw in rendered_words:
                col = "#FFD02A" if rw["is_active"] else ("#00F0FF" if rw["is_num"] else "#FFFFFF")
                y_offset = (cy - max_h // 2) - (2 if rw["is_active"] else 0)

                # Thin, ultra-crisp outline only (NO drop shadow)
                draw.text((cur_x, y_offset), rw["text"], font=rw["font"], fill=col, stroke_width=2, stroke_fill="#0d1117")
                cur_x += rw["adv_w"] + space_w
            return pil_img

        # -------------------------------------------------------------
        # STYLE 4: CLASSIC (High-Contrast Bold Outline + Drop Shadow)
        # -------------------------------------------------------------
        else:
            draw = ImageDraw.Draw(pil_img)
            # Drop shadow pass
            cur_x = start_x
            for rw in rendered_words:
                y_offset = (cy - max_h // 2) - (4 if rw["is_active"] else 0)
                draw.text((cur_x + 2, y_offset + 2), rw["text"], font=rw["font"], fill="black", stroke_width=5, stroke_fill="black")
                cur_x += rw["adv_w"] + space_w

            # Main text pass
            cur_x = start_x
            for rw in rendered_words:
                col = "#FFD02A" if rw["is_active"] else ("#00F0FF" if rw["is_num"] else "#FFFFFF")
                y_offset = (cy - max_h // 2) - (4 if rw["is_active"] else 0)
                draw.text((cur_x, y_offset), rw["text"], font=rw["font"], fill=col, stroke_width=4, stroke_fill="black")
                cur_x += rw["adv_w"] + space_w
            return pil_img
