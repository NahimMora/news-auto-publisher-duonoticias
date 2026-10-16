import os
import re
import time
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def sanitize_filename(name):
    """Limpia nombres de archivo."""
    name = name.replace(' ', '_')
    name = re.sub(r'[^\w\-_.]', '', name)
    return name


def process_image(url_or_path, filename, folder, target_width=700, max_width=1080):
    """
    Descarga o abre una imagen, garantiza que tenga al menos 'target_width' de ancho,
    la redimensiona si excede max_width y la guarda como JPEG.
    """
    import requests
    from io import BytesIO
    from urllib.parse import urlparse
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    os.makedirs(folder, exist_ok=True)
    filename = sanitize_filename(filename)
    output_path = os.path.join(folder, filename)

    try:
        if str(url_or_path).startswith("http"):
            parsed = urlparse(str(url_or_path))
            referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else "https://www.paparazzi.com.ar/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            }
            last_exc = None
            for attempt in range(3):
                try:
                    resp = requests.get(url_or_path, headers=headers, verify=False, timeout=15)
                    resp.raise_for_status()
                    img = Image.open(BytesIO(resp.content))
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise last_exc
        else:
            img = Image.open(url_or_path)

        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size

        if w < target_width:
            new_h = int(h * (target_width / w))
            img = img.resize((target_width, new_h), Image.LANCZOS)
            w, h = img.size

        if w > max_width:
            new_h = int(h * (max_width / w))
            img = img.resize((max_width, new_h), Image.LANCZOS)

        img.save(output_path, format="JPEG", quality=95)
        return os.path.abspath(output_path)

    except Exception as e:
        print(f"[ERROR] Could not process image: {url_or_path} ({e})")
        return None


def optimize_image(image_path, output_filename, folder, max_size_kb=50, initial_quality=85):
    """
    Optimiza una imagen garantizando que pese menos de 'max_size_kb' KB.
    Reduce la calidad progresivamente hasta lograrlo.
    """
    from io import BytesIO

    try:
        os.makedirs(folder, exist_ok=True)
        output_path = os.path.join(folder, sanitize_filename(output_filename))
        img = Image.open(image_path)

        if img.mode != "RGB":
            img = img.convert("RGB")

        quality = initial_quality
        buffer = BytesIO()

        while quality > 5:
            buffer.seek(0)
            buffer.truncate()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            size_kb = len(buffer.getvalue()) / 1024
            if size_kb <= max_size_kb:
                break
            quality -= 5

        with open(output_path, "wb") as f:
            f.write(buffer.getvalue())

        return os.path.abspath(output_path)

    except Exception as e:
        print(f"[ERROR] Could not optimize image ({image_path}): {e}")
        return None


def normalize_for_instagram_blur(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    blur_radius=25,
    watermark_path=None,
    watermark_opacity=0.25,
    watermark_scale=0.6,
    watermark_position="center",
    watermark_margin=20,
    title_text=None,
    title_font_path=None,
    title_color=(255, 255, 255),
    title_stroke_color=(0, 0, 0),
    title_stroke_width=4,
    title_shadow_color=(0, 0, 0),
    title_shadow_offset=(3, 3),
    theme_gray_top=(35, 35, 35),
    theme_gray_bottom=(90, 90, 90),
    **kwargs,
):
    """
    Normaliza la imagen a 4:5 con:
    - Mitad superior: imagen principal (recorte tipo cover).
    - Mitad inferior: fondo con degradado gris y titulo en mayusculas.
    """
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_ig.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        half_h = target_h // 2

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            src_w, src_h = img.size

            bg = img.resize((target_w, target_h), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

            scale = max(target_w / src_w, half_h / src_h)
            fg_w = int(src_w * scale)
            fg_h = int(src_h * scale)
            fg = img.resize((fg_w, fg_h), Image.LANCZOS)
            left = max(0, (fg_w - target_w) // 2)
            top = max(0, (fg_h - half_h) // 2)
            fg = fg.crop((left, top, left + target_w, top + half_h))
            bg.paste(fg, (0, 0))

            grad = Image.new("RGB", (target_w, half_h), theme_gray_top)
            grad_draw = ImageDraw.Draw(grad)
            for y in range(half_h):
                t = y / max(1, half_h - 1)
                r = int(theme_gray_top[0] + (theme_gray_bottom[0] - theme_gray_top[0]) * t)
                g = int(theme_gray_top[1] + (theme_gray_bottom[1] - theme_gray_top[1]) * t)
                b = int(theme_gray_top[2] + (theme_gray_bottom[2] - theme_gray_top[2]) * t)
                grad_draw.line([(0, y), (target_w, y)], fill=(r, g, b))
            bg.paste(grad, (0, half_h))

            if title_text:
                draw = ImageDraw.Draw(bg)
                safe_text = title_text.upper().strip()
                pad_x = 50
                pad_y = 40
                max_width = target_w - (pad_x * 2)
                max_height = half_h - (pad_y * 2)
                font, lines, line_height = _fit_title_text(
                    draw,
                    safe_text,
                    title_font_path,
                    max_width,
                    max_height,
                    base_font_size=64,
                )
                total_height = line_height * len(lines)
                start_y = half_h + ((half_h - total_height) // 2)
                for line in lines:
                    line_w = draw.textbbox((0, 0), line, font=font)[2]
                    x = (target_w - line_w) // 2
                    y = start_y
                    if title_shadow_offset != (0, 0):
                        sx = x + title_shadow_offset[0]
                        sy = y + title_shadow_offset[1]
                        draw.text(
                            (sx, sy),
                            line,
                            font=font,
                            fill=title_shadow_color,
                            stroke_width=title_stroke_width,
                            stroke_fill=title_stroke_color,
                        )
                    draw.text(
                        (x, y),
                        line,
                        font=font,
                        fill=title_color,
                        stroke_width=title_stroke_width,
                        stroke_fill=title_stroke_color,
                    )
                    start_y += line_height

            if watermark_path and os.path.exists(watermark_path):
                try:
                    with Image.open(watermark_path) as wm:
                        if wm.mode != "RGBA":
                            wm = wm.convert("RGBA")

                        wm_w = int(target_w * watermark_scale)
                        wm_h = int(wm.size[1] * (wm_w / wm.size[0]))
                        wm = wm.resize((wm_w, wm_h), Image.LANCZOS)

                        if watermark_opacity < 1:
                            alpha = wm.split()[3]
                            alpha = alpha.point(lambda p: int(p * watermark_opacity))
                            wm.putalpha(alpha)

                        base_rgba = bg.convert("RGBA")
                        if watermark_position == "top_right":
                            wm_x = target_w - wm_w - watermark_margin
                            wm_y = watermark_margin
                        elif watermark_position == "top_left":
                            wm_x = watermark_margin
                            wm_y = watermark_margin
                        elif watermark_position == "bottom_right":
                            wm_x = target_w - wm_w - watermark_margin
                            wm_y = target_h - wm_h - watermark_margin
                        elif watermark_position == "bottom_left":
                            wm_x = watermark_margin
                            wm_y = target_h - wm_h - watermark_margin
                        else:
                            wm_x = (target_w - wm_w) // 2
                            wm_y = (target_h - wm_h) // 2
                        base_rgba.paste(wm, (wm_x, wm_y), wm)
                        bg = base_rgba.convert("RGB")
                except Exception as e:
                    print(f"[WARN] Watermark error: {e}")

            bg.save(output_path, format="JPEG", quality=90, subsampling=2)

        return os.path.abspath(output_path)
    except Exception as e:
        print(f"[ERROR] Could not normalize image with blur ({image_path}): {e}")
        return None


def _load_title_font(font_path, font_size):
    """Carga fuente TrueType o fallback."""
    try:
        if font_path and os.path.exists(font_path):
            return ImageFont.truetype(font_path, font_size)
    except Exception:
        pass
    try:
        return ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    """Divide texto en líneas según ancho máximo."""
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test_line = f"{current} {word}"
        if draw.textbbox((0, 0), test_line, font=font)[2] <= max_width:
            current = test_line
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_title_text(draw, text, font_path, max_width, max_height, base_font_size=84):
    """Ajusta tamaño de fuente para que el texto quepa en el espacio disponible."""
    font_size = base_font_size
    while font_size > 10:
        font = _load_title_font(font_path, font_size)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
        total_height = line_height * len(lines)
        if lines and total_height <= max_height:
            return font, lines, line_height
        font_size -= 2
    font = _load_title_font(font_path, 10)
    lines = _wrap_text(draw, text, font, max_width)
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    return font, lines, line_height


def _resize_cover(img, target_size):
    target_w, target_h = target_size
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _resize_contain(img, max_size):
    max_w, max_h = max_size
    src_w, src_h = img.size
    scale = min(max_w / src_w, max_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _fit_title_text_max_lines(draw, text, font_path, max_width, max_height, base_font_size=92, min_font_size=34, max_lines=4):
    font_size = base_font_size
    best = None
    while font_size >= min_font_size:
        font = _load_title_font(font_path, font_size)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
        total_height = line_height * len(lines)
        if lines and len(lines) <= max_lines and total_height <= max_height:
            return font, lines, line_height
        if lines and total_height <= max_height:
            best = (font, lines, line_height)
        font_size -= 2
    if best:
        return best
    return _fit_title_text(draw, text, font_path, max_width, max_height, base_font_size=min_font_size)


def _fit_title_text_spaced(
    draw,
    text,
    font_path,
    max_width,
    max_height,
    base_font_size=78,
    min_font_size=32,
    max_lines=4,
    line_spacing=10,
):
    font_size = base_font_size
    best = None
    while font_size >= min_font_size:
        font = _load_title_font(font_path, font_size)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
        total_height = line_height * len(lines) + line_spacing * max(0, len(lines) - 1)
        if lines and len(lines) <= max_lines and total_height <= max_height:
            return font, lines, line_height, line_spacing
        if lines and total_height <= max_height:
            best = (font, lines, line_height, line_spacing)
        font_size -= 2
    if best:
        return best
    font = _load_title_font(font_path, min_font_size)
    lines = _wrap_text(draw, text, font, max_width)
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    return font, lines, line_height, line_spacing


def _theme_palette(content_theme=None):
    theme = str(content_theme or "default").strip().lower()
    palettes = {
        "showbiz": {
            "kicker": "ESPECTACULOS",
            "panel": (16, 12, 28),
            "accent": (245, 178, 18),
            "top_tint": (20, 12, 28),
        },
        "politics": {
            "kicker": "POLITICA",
            "panel": (14, 20, 28),
            "accent": (70, 166, 224),
            "top_tint": (10, 22, 34),
        },
        "business": {
            "kicker": "ECONOMIA",
            "panel": (12, 23, 22),
            "accent": (68, 205, 148),
            "top_tint": (8, 26, 22),
        },
        "sports": {
            "kicker": "DEPORTES",
            "panel": (18, 24, 18),
            "accent": (176, 218, 92),
            "top_tint": (14, 24, 16),
        },
        "sensitive": {
            "kicker": "INFORMACION",
            "panel": (18, 18, 20),
            "accent": (214, 214, 214),
            "top_tint": (14, 14, 16),
        },
        "default": {
            "kicker": "TENDENCIA",
            "panel": (18, 14, 30),
            "accent": (245, 178, 18),
            "top_tint": (18, 12, 28),
        },
    }
    return palettes.get(theme, palettes["default"])


def _apply_subtle_texture(canvas_rgba, alpha=9):
    width, height = canvas_rgba.size
    try:
        noise = Image.effect_noise((max(1, width // 3), max(1, height // 3)), 18).convert("L")
        noise = noise.resize((width, height), Image.BILINEAR)
        texture = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        texture.putalpha(noise.point(lambda p: int(abs(p - 128) * alpha / 128)))
        canvas_rgba.alpha_composite(texture)
    except Exception:
        return canvas_rgba
    return canvas_rgba


def _apply_native_duo_branding(canvas, title_font_path=None, accent_color=(245, 178, 18), compact=False, overlay_template_path=None):
    base = canvas.convert("RGBA")
    width, height = base.size
    if overlay_template_path and os.path.exists(overlay_template_path):
        try:
            with Image.open(overlay_template_path) as overlay:
                if overlay.mode != "RGBA":
                    overlay = overlay.convert("RGBA")
                overlay = overlay.resize((width, height), Image.LANCZOS)
                base.alpha_composite(overlay, dest=(0, 0))
                return base.convert("RGB")
        except Exception as e:
            print(f"[WARN] Branding overlay error: {e}")

    draw = ImageDraw.Draw(base)
    brand_text = "duonoticias"
    font = _load_title_font(title_font_path, 34 if compact else 38)
    bbox = draw.textbbox((0, 0), brand_text, font=font)
    brand_x = (width - (bbox[2] - bbox[0])) // 2
    brand_y = height - (76 if compact else 82)
    shadow = (0, 0, 0, 95)
    draw.text((brand_x + 2, brand_y + 2), brand_text, font=font, fill=shadow)
    draw.text((brand_x, brand_y), brand_text, font=font, fill=accent_color + (255,))
    return base.convert("RGB")


def _normalize_mojibake(text):
    if not text:
        return text
    # Try to repair common mojibake produced by UTF-8 bytes decoded as Latin-1.
    try:
        fixed = text.encode("latin1").decode("utf-8")
        if fixed != text and "\ufffd" not in fixed:
            text = fixed
    except Exception:
        pass

    for q in [
        "“", "”", "„", "‟",
        "‘", "’", "‚",
        "«", "»", "‹", "›",
        "「", "」", "『", "』",
    ]:
        if q in text:
            text = text.replace(q, '"')
    return text


def _segment_title_line(line):
    """Divide una linea en segmentos (texto, color_hex) segun signos especiales."""
    highlight = "#ffb700"
    normal = None
    line = _normalize_mojibake(line)
    inverted_excl = "¡"
    inverted_q = "¿"

    n = len(line)
    highlight_mask = [False] * n

    # ?...! and ?...?
    for start_sym, end_sym in ((inverted_excl, "!"), (inverted_q, "?")):
        i = 0
        while i < n:
            s = line.find(start_sym, i)
            if s == -1:
                break
            e = line.find(end_sym, s + 1)
            if e == -1:
                i = s + 1
                continue
            for idx in range(s, e + 1):
                highlight_mask[idx] = True
            i = e + 1

    # All quotes are normalized to "
    indices = [i for i, ch in enumerate(line) if ch == '"']
    for a, b in zip(indices[0::2], indices[1::2]):
        for idx in range(a, b + 1):
            highlight_mask[idx] = True

    # Build segments
    segments = []
    if not line:
        return segments
    current_color = highlight if highlight_mask[0] else normal
    buf = [line[0]]
    for i in range(1, n):
        c = line[i]
        color = highlight if highlight_mask[i] else normal
        if color == current_color:
            buf.append(c)
        else:
            segments.append(("".join(buf), current_color))
            buf = [c]
            current_color = color
    if buf:
        segments.append(("".join(buf), current_color))
    return segments


def normalize_for_instagram_news_card(

    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    title_text=None,
    corner_logo_path=None,
    slide_icon_path=None,
    slide_icon_tint=(237, 22, 102),
    slide_icon_offset_right=140,
    center_logo_path=None,
    footer_logo_path=None,
    title_font_path=None,
    title_color=(255, 255, 255),
    title_shadow_offset=(0, 3),
    title_shadow_color=(0, 0, 0),
    top_color=(45, 45, 45),
    bottom_color=(45, 45, 45),
    connector_fade_alpha=250,
    top_fade_alpha=180,
    connector_fade_color=(20, 20, 20),
    top_fade_color=(20, 20, 20),
    footer_logo_scale=0.6,
    footer_logo_margin=30,
    overlay_template_path=None,
    watermark_image_path=None,
    watermark_image_opacity=0.5,
    watermark_image_scale=0.75,
    title_stroke_width=4,
    title_bold_dilate=0,
    **kwargs,
):
    """
    Card 4:5 con:
    - Mitad superior con imagen tipo cover sobre blur (sin recorte visible).
    - Mitad inferior rosa solido.
    - Degradado intenso rosa->transparente para conectar ambas mitades.
    - Logo cuadrado chico arriba a la derecha.
    - Logo principal centrado en la mitad exacta.
    - Titulo inferior centrado, blanco con borde negro y sombra.
    """
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_news.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        top_h = int(target_h * 0.55)
        bottom_h = target_h - top_h

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
            bg = img.resize((target_w, target_h), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
            canvas.paste(bg, (0, 0))

            padding = 20
            area_w = target_w
            area_h = top_h - (padding * 2)
            src_w, src_h = img.size
            scale = area_w / src_w
            new_w = int(src_w * scale)
            new_h = int(src_h * scale)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            if new_h > area_h:
                crop_top = (new_h - area_h) // 2
                resized = resized.crop((0, crop_top, new_w, crop_top + area_h))
                new_h = area_h
            paste_x = (target_w - new_w) // 2
            paste_y = padding + ((area_h - new_h) // 2)
            canvas.paste(resized, (paste_x, paste_y))

            bottom_panel = Image.new("RGBA", (target_w, bottom_h), (28, 18, 45, 255))
            border_draw = ImageDraw.Draw(bottom_panel)
            border_thickness = 8
            border_draw.rectangle(
                [0, 0, target_w, border_thickness],
                fill=(255, 255, 255, 230),
            )
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.alpha_composite(bottom_panel, dest=(0, top_h))
            canvas = canvas_rgba.convert("RGB")

            connector_h = int(top_h * 0.25)
            connector = Image.new("RGBA", (target_w, connector_h), (0, 0, 0, 0))
            connector_draw = ImageDraw.Draw(connector)
            for y in range(connector_h):
                t = y / max(1, connector_h - 1)
                alpha = int(connector_fade_alpha * t)
                color = (connector_fade_color[0], connector_fade_color[1], connector_fade_color[2], alpha)
                connector_draw.line([(0, y), (target_w, y)], fill=color)
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.alpha_composite(connector, dest=(0, top_h - connector_h))
            canvas = canvas_rgba.convert("RGB")

            top_fade_h = 100
            top_fade = Image.new("RGBA", (target_w, top_fade_h), (0, 0, 0, 0))
            top_fade_draw = ImageDraw.Draw(top_fade)
            for y in range(top_fade_h):
                t = y / max(1, top_fade_h - 1)
                alpha = int(top_fade_alpha * (1 - t))
                color = (top_fade_color[0], top_fade_color[1], top_fade_color[2], alpha)
                top_fade_draw.line([(0, y), (target_w, y)], fill=color)
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.alpha_composite(top_fade, dest=(0, 0))
            canvas = canvas_rgba.convert("RGB")

        if corner_logo_path and os.path.exists(corner_logo_path):
            try:
                with Image.open(corner_logo_path) as logo:
                    if logo.mode != "RGBA":
                        logo = logo.convert("RGBA")
                    logo_size = 90
                    logo_h = int(logo.size[1] * (logo_size / logo.size[0]))
                    logo = logo.resize((logo_size, logo_h), Image.LANCZOS)
                    logo_x = 30
                    logo_y = 45
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(logo, (logo_x, logo_y), logo)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Corner logo error: {e}")

        if slide_icon_path and os.path.exists(slide_icon_path):
            try:
                with Image.open(slide_icon_path) as icon:
                    if icon.mode != "RGBA":
                        icon = icon.convert("RGBA")
                    icon_size = 120
                    icon_h = int(icon.size[1] * (icon_size / icon.size[0]))
                    icon = icon.resize((icon_size, icon_h), Image.LANCZOS)
                    if slide_icon_tint:
                        tint = Image.new("RGBA", icon.size, slide_icon_tint + (255,))
                        alpha = icon.split()[3]
                        tint.putalpha(alpha)
                        icon = tint
                    icon_x = target_w - icon_size - slide_icon_offset_right
                    icon_y = 30
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(icon, (icon_x, icon_y), icon)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Slide icon error: {e}")

        if center_logo_path and os.path.exists(center_logo_path):
            try:
                with Image.open(center_logo_path) as logo:
                    if logo.mode != "RGBA":
                        logo = logo.convert("RGBA")
                    logo_h = 70
                    logo_w = int(logo.size[0] * (logo_h / logo.size[1]))
                    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
                    logo_x = (target_w - logo_w) // 2
                    logo_y = (target_h - logo_h) // 2 + 20
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(logo, (logo_x, logo_y), logo)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Center logo error: {e}")

        if footer_logo_path and os.path.exists(footer_logo_path):
            try:
                with Image.open(footer_logo_path) as footer_logo:
                    if footer_logo.mode != "RGBA":
                        footer_logo = footer_logo.convert("RGBA")
                    footer_w = int(target_w * footer_logo_scale)
                    footer_h = int(footer_logo.size[1] * (footer_w / footer_logo.size[0]))
                    footer_logo = footer_logo.resize((footer_w, footer_h), Image.LANCZOS)
                    footer_x = (target_w - footer_w) // 2
                    footer_y = target_h - footer_h - (footer_logo_margin - 15)
                    canvas_rgba = canvas.convert("RGBA")
                    footer_bg_margin = 12
                    footer_bg = Image.new(
                        "RGBA",
                        (target_w, footer_h + (footer_bg_margin * 2)),
                        (237, 22, 102, 255),
                    )
                    canvas_rgba.alpha_composite(footer_bg, dest=(0, target_h - footer_bg.size[1]))
                    canvas_rgba.paste(footer_logo, (footer_x, footer_y), footer_logo)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Footer logo error: {e}")

        if title_text:
            draw = ImageDraw.Draw(canvas)
            safe_text = title_text.upper().strip()
            title_padding_x = 70
            title_padding_top = 20
            title_padding_bottom = 100
            title_max_w = target_w - (title_padding_x * 2)
            title_max_h = bottom_h - (title_padding_top + title_padding_bottom)
            font, lines, line_height = _fit_title_text(
                draw,
                safe_text,
                title_font_path,
                title_max_w,
                title_max_h,
                base_font_size=128,
            )
            total_height = line_height * len(lines)
            start_y = top_h + title_padding_top + ((title_max_h - total_height) // 2)
            if not title_bold_dilate:
                try:
                    title_bold_dilate = int(os.getenv("IG_TITLE_BOLD_DILATE", "2"))
                except Exception:
                    title_bold_dilate = 0
            try:
                bold_px = int(title_bold_dilate)
            except Exception:
                bold_px = 0
            if bold_px > 4:
                bold_px = 4
            for line in lines:
                segments = _segment_title_line(line)
                line_w = sum(draw.textbbox((0, 0), seg_text, font=font)[2] for seg_text, _ in segments)
                x = (target_w - line_w) // 2
                y = start_y
                if title_shadow_offset and title_shadow_offset != (0, 0):
                    sx = x + title_shadow_offset[0]
                    sy = y + title_shadow_offset[1]
                    cursor = sx
                    for seg_text, _ in segments:
                        draw.text(
                            (cursor, sy),
                            seg_text,
                            font=font,
                            fill=title_shadow_color,
                            stroke_width=title_stroke_width,
                            stroke_fill=(0, 0, 0),
                        )
                        cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                if bold_px > 0:
                    for dx in range(-bold_px, bold_px + 1):
                        cursor = x + dx
                        for seg_text, seg_color in segments:
                            draw.text(
                                (cursor, y),
                                seg_text,
                                font=font,
                                fill=seg_color or title_color,
                                stroke_width=title_stroke_width,
                                stroke_fill=(0, 0, 0),
                            )
                            cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                else:
                    cursor = x
                    for seg_text, seg_color in segments:
                        draw.text(
                            (cursor, y),
                            seg_text,
                            font=font,
                            fill=seg_color or title_color,
                            stroke_width=title_stroke_width,
                            stroke_fill=(0, 0, 0),
                        )
                        cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                start_y += line_height

        if overlay_template_path and os.path.exists(overlay_template_path):
            try:
                with Image.open(overlay_template_path) as overlay:
                    if overlay.mode != "RGBA":
                        overlay = overlay.convert("RGBA")
                    overlay = overlay.resize((target_w, target_h), Image.LANCZOS)
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.alpha_composite(overlay, dest=(0, 0))
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Overlay error: {e}")

        canvas.save(output_path, format="JPEG", quality=92, subsampling=2)
        return os.path.abspath(output_path)

    except Exception as e:
        print(f"[ERROR] Could not create news card ({image_path}): {e}")
        return None


def normalize_for_instagram_pink_card(*args, **kwargs):
    return normalize_for_instagram_news_card(*args, **kwargs)


def normalize_for_instagram_premium_v2_card(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    title_text=None,
    kicker_text=None,
    content_theme=None,
    title_font_path=None,
    title_color=(255, 255, 255),
    title_shadow_color=(0, 0, 0),
    title_stroke_width=1,
    overlay_template_path=None,
    **kwargs,
):
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_premium_v2.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        palette = _theme_palette(content_theme)
        accent = palette["accent"]
        panel_color = palette["panel"]
        top_tint = palette["top_tint"]
        kicker = (kicker_text or palette["kicker"]).strip().upper()

        photo_h = int(target_h * 0.735)
        panel_y = photo_h - 30
        panel_h = target_h - panel_y

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            bg = _resize_cover(img, (target_w, target_h)).filter(ImageFilter.GaussianBlur(radius=16))
            canvas_rgba = bg.convert("RGBA")
            canvas_rgba.alpha_composite(Image.new("RGBA", (target_w, target_h), top_tint + (74,)))

            foreground = _resize_cover(img, (target_w, photo_h))
            canvas_rgba.paste(foreground.convert("RGBA"), (0, 0))

            fade_h = 210
            fade = Image.new("RGBA", (target_w, fade_h), (0, 0, 0, 0))
            fade_draw = ImageDraw.Draw(fade)
            for y in range(fade_h):
                alpha = int(112 * (y / max(1, fade_h - 1)))
                fade_draw.line([(0, y), (target_w, y)], fill=(0, 0, 0, alpha))
            canvas_rgba.alpha_composite(fade, dest=(0, photo_h - fade_h))

            panel = Image.new("RGBA", (target_w, panel_h), panel_color + (246,))
            panel_draw = ImageDraw.Draw(panel)
            panel_draw.rectangle([0, 0, target_w, 4], fill=accent + (255,))
            panel_draw.rectangle([0, 4, target_w, 5], fill=(255, 255, 255, 62))
            canvas_rgba.alpha_composite(panel, dest=(0, panel_y))
            canvas_rgba = _apply_subtle_texture(canvas_rgba, alpha=8)
            canvas = canvas_rgba.convert("RGB")

        draw = ImageDraw.Draw(canvas)
        left_x = 72
        right_x = target_w - 72
        kicker_y = panel_y + 42
        if kicker:
            kicker_font = _load_title_font(title_font_path, 28)
            kb = draw.textbbox((0, 0), kicker, font=kicker_font)
            chip_w = (kb[2] - kb[0]) + 34
            chip_h = 40
            draw.rounded_rectangle(
                [left_x, kicker_y, left_x + chip_w, kicker_y + chip_h],
                radius=6,
                fill=accent + (255,),
            )
            draw.text(
                (left_x + 17, kicker_y + 4),
                kicker,
                font=kicker_font,
                fill=(22, 16, 30),
            )

        if title_text:
            safe_text = _normalize_mojibake(str(title_text)).strip()
            title_y = kicker_y + 66
            title_max_w = right_x - left_x
            title_max_h = max(170, target_h - title_y - 128)
            font, lines, line_height, line_spacing = _fit_title_text_spaced(
                draw,
                safe_text,
                title_font_path,
                title_max_w,
                title_max_h,
                base_font_size=78,
                min_font_size=34,
                max_lines=4,
                line_spacing=10,
            )
            y = title_y
            for line in lines[:4]:
                segments = _segment_title_line(line)
                cursor = left_x
                for seg_text, _ in segments:
                    draw.text(
                        (cursor + 2, y + 2),
                        seg_text,
                        font=font,
                        fill=title_shadow_color,
                        stroke_width=title_stroke_width,
                        stroke_fill=(0, 0, 0),
                    )
                    cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                cursor = left_x
                for seg_text, seg_color in segments:
                    draw.text(
                        (cursor, y),
                        seg_text,
                        font=font,
                        fill=seg_color or title_color,
                        stroke_width=title_stroke_width,
                        stroke_fill=(0, 0, 0),
                    )
                    cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                y += line_height + line_spacing

        canvas = _apply_native_duo_branding(
            canvas,
            title_font_path=title_font_path,
            accent_color=accent,
            overlay_template_path=overlay_template_path,
        )
        canvas.save(output_path, format="JPEG", quality=94, subsampling=2)
        return os.path.abspath(output_path)
    except Exception as e:
        print(f"[ERROR] Could not create premium v2 card ({image_path}): {e}")
        return None


def normalize_for_instagram_premium_v2_secondary(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    content_theme=None,
    title_font_path=None,
    frame_color=(255, 255, 255),
    overlay_template_path=None,
    **kwargs,
):
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_premium_v2.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        palette = _theme_palette(content_theme)
        accent = palette["accent"]
        top_tint = palette["top_tint"]

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            bg = _resize_cover(img, (target_w, target_h)).filter(ImageFilter.GaussianBlur(radius=15))
            canvas_rgba = bg.convert("RGBA")
            canvas_rgba.alpha_composite(Image.new("RGBA", (target_w, target_h), top_tint + (82,)))
            canvas_rgba = _apply_subtle_texture(canvas_rgba, alpha=7)

            max_w = target_w - 78
            max_h = target_h - 230
            foreground = _resize_contain(img, (max_w, max_h))
            fg_x = (target_w - foreground.size[0]) // 2
            fg_y = max(78, (target_h - foreground.size[1]) // 2 - 26)

            shadow = Image.new("RGBA", (foreground.size[0] + 38, foreground.size[1] + 38), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rounded_rectangle(
                [19, 19, shadow.size[0] - 19, shadow.size[1] - 19],
                radius=8,
                fill=(0, 0, 0, 105),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
            canvas_rgba.alpha_composite(shadow, dest=(fg_x - 19, fg_y - 19))
            canvas_rgba.paste(foreground.convert("RGBA"), (fg_x, fg_y))

            border = Image.new("RGBA", foreground.size, (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border)
            border_draw.rectangle(
                [0, 0, foreground.size[0] - 1, foreground.size[1] - 1],
                outline=frame_color + (145,),
                width=2,
            )
            border_draw.rectangle(
                [0, foreground.size[1] - 5, foreground.size[0], foreground.size[1] - 1],
                fill=accent + (255,),
            )
            canvas_rgba.alpha_composite(border, dest=(fg_x, fg_y))
            canvas = canvas_rgba.convert("RGB")

        canvas = _apply_native_duo_branding(
            canvas,
            title_font_path=title_font_path,
            accent_color=accent,
            compact=True,
            overlay_template_path=overlay_template_path,
        )
        canvas.save(output_path, format="JPEG", quality=94, subsampling=2)
        return os.path.abspath(output_path)
    except Exception as e:
        print(f"[ERROR] Could not create premium v2 secondary ({image_path}): {e}")
        return None


def normalize_for_instagram_premium_card(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    title_text=None,
    title_font_path=None,
    title_color=(255, 255, 255),
    title_shadow_offset=(0, 2),
    title_shadow_color=(0, 0, 0),
    panel_color=(18, 14, 30),
    accent_color=(245, 178, 18),
    overlay_template_path=None,
    title_stroke_width=2,
    title_bold_dilate=1,
    **kwargs,
):
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_premium.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        photo_h = int(target_h * 0.68)
        panel_y = photo_h - 22
        panel_h = target_h - panel_y

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            bg = _resize_cover(img, (target_w, target_h))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=20))
            shade = Image.new("RGBA", (target_w, target_h), (6, 5, 10, 92))
            canvas_rgba = bg.convert("RGBA")
            canvas_rgba.alpha_composite(shade)

            foreground = _resize_contain(img, (target_w, photo_h))
            fg_x = (target_w - foreground.size[0]) // 2
            fg_y = (photo_h - foreground.size[1]) // 2
            canvas_rgba.paste(foreground.convert("RGBA"), (fg_x, fg_y))

            photo_gradient_h = 190
            gradient = Image.new("RGBA", (target_w, photo_gradient_h), (0, 0, 0, 0))
            gradient_draw = ImageDraw.Draw(gradient)
            for y in range(photo_gradient_h):
                alpha = int(120 * (y / max(1, photo_gradient_h - 1)))
                gradient_draw.line([(0, y), (target_w, y)], fill=(0, 0, 0, alpha))
            canvas_rgba.alpha_composite(gradient, dest=(0, max(0, photo_h - photo_gradient_h)))

            panel = Image.new("RGBA", (target_w, panel_h), panel_color + (246,))
            panel_draw = ImageDraw.Draw(panel)
            panel_draw.rectangle([0, 0, target_w, 5], fill=accent_color + (255,))
            panel_draw.rectangle([0, 5, target_w, 7], fill=(255, 255, 255, 90))
            canvas_rgba.alpha_composite(panel, dest=(0, panel_y))
            canvas = canvas_rgba.convert("RGB")

        if title_text:
            draw = ImageDraw.Draw(canvas)
            safe_text = _normalize_mojibake(str(title_text)).upper().strip()
            title_x = 76
            title_y = panel_y + 64
            title_max_w = target_w - (title_x * 2)
            title_max_h = max(160, target_h - title_y - 160)
            font, lines, line_height = _fit_title_text_max_lines(
                draw,
                safe_text,
                title_font_path,
                title_max_w,
                title_max_h,
                base_font_size=92,
                min_font_size=34,
                max_lines=4,
            )
            total_height = line_height * len(lines)
            y = title_y + max(0, (title_max_h - total_height) // 2)
            try:
                bold_px = max(0, min(3, int(title_bold_dilate)))
            except Exception:
                bold_px = 0
            for line in lines:
                segments = _segment_title_line(line)
                x = title_x
                if title_shadow_offset and title_shadow_offset != (0, 0):
                    cursor = x + title_shadow_offset[0]
                    for seg_text, _ in segments:
                        draw.text(
                            (cursor, y + title_shadow_offset[1]),
                            seg_text,
                            font=font,
                            fill=title_shadow_color,
                            stroke_width=title_stroke_width,
                            stroke_fill=(0, 0, 0),
                        )
                        cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                for dx in range(-bold_px, bold_px + 1):
                    cursor = x + dx
                    for seg_text, seg_color in segments:
                        draw.text(
                            (cursor, y),
                            seg_text,
                            font=font,
                            fill=seg_color or title_color,
                            stroke_width=title_stroke_width,
                            stroke_fill=(0, 0, 0),
                        )
                        cursor += draw.textbbox((0, 0), seg_text, font=font)[2]
                y += line_height

        if overlay_template_path and os.path.exists(overlay_template_path):
            try:
                with Image.open(overlay_template_path) as overlay:
                    if overlay.mode != "RGBA":
                        overlay = overlay.convert("RGBA")
                    overlay = overlay.resize((target_w, target_h), Image.LANCZOS)
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.alpha_composite(overlay, dest=(0, 0))
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Overlay error: {e}")

        canvas.save(output_path, format="JPEG", quality=93, subsampling=2)
        return os.path.abspath(output_path)
    except Exception as e:
        print(f"[ERROR] Could not create premium card ({image_path}): {e}")
        return None


def normalize_for_instagram_premium_secondary(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    blur_radius=18,
    overlay_template_path=None,
    frame_color=(255, 255, 255),
    **kwargs,
):
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_premium.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size
        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            bg = _resize_cover(img, (target_w, target_h)).filter(ImageFilter.GaussianBlur(radius=blur_radius))
            canvas_rgba = bg.convert("RGBA")
            canvas_rgba.alpha_composite(Image.new("RGBA", (target_w, target_h), (8, 6, 12, 78)))

            max_w = target_w - 92
            max_h = target_h - 210
            foreground = _resize_contain(img, (max_w, max_h))
            fg_x = (target_w - foreground.size[0]) // 2
            fg_y = max(54, (target_h - foreground.size[1]) // 2 - 18)

            shadow = Image.new("RGBA", (foreground.size[0] + 28, foreground.size[1] + 28), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rectangle([14, 14, shadow.size[0] - 14, shadow.size[1] - 14], fill=(0, 0, 0, 95))
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=14))
            canvas_rgba.alpha_composite(shadow, dest=(fg_x - 14, fg_y - 14))
            canvas_rgba.paste(foreground.convert("RGBA"), (fg_x, fg_y))

            border = Image.new("RGBA", foreground.size, (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border)
            border_draw.rectangle(
                [0, 0, foreground.size[0] - 1, foreground.size[1] - 1],
                outline=frame_color + (130,),
                width=2,
            )
            canvas_rgba.alpha_composite(border, dest=(fg_x, fg_y))
            canvas = canvas_rgba.convert("RGB")

        if overlay_template_path and os.path.exists(overlay_template_path):
            try:
                with Image.open(overlay_template_path) as overlay:
                    if overlay.mode != "RGBA":
                        overlay = overlay.convert("RGBA")
                    overlay = overlay.resize((target_w, target_h), Image.LANCZOS)
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.alpha_composite(overlay, dest=(0, 0))
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Overlay error: {e}")

        canvas.save(output_path, format="JPEG", quality=93, subsampling=2)
        return os.path.abspath(output_path)
    except Exception as e:
        print(f"[ERROR] Could not create premium secondary ({image_path}): {e}")
        return None


def normalize_for_instagram_carousel_secondary(
    image_path,
    output_filename=None,
    folder=None,
    target_size=(1080, 1350),
    corner_logo_path=None,
    corner_logo_size=90,
    corner_logo_margin=30,
    bottom_logo_path=None,
    bottom_logo_height=90,
    bottom_logo_margin=40,
    blur_radius=22,
    overlay_template_path=None,
    watermark_image_path=None,
    watermark_image_opacity=0.5,
    watermark_image_scale=0.75,
    **kwargs,
):
    """
    Normaliza la imagen a 4:5 con fondo blur y logos:
    - Logo cuadrado en esquina superior derecha.
    - Logo HolaSalta centrado abajo.
    """
    try:
        if not os.path.exists(image_path):
            print(f"[ERROR] Image not found: {image_path}")
            return None

        if folder is None:
            folder = os.path.dirname(image_path)
        os.makedirs(folder, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if not output_filename:
            output_filename = f"{base_name}_ig.jpg"
        output_path = os.path.join(folder, sanitize_filename(output_filename))

        target_w, target_h = target_size

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            bg = img.resize((target_w, target_h), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

            src_w, src_h = img.size
            scale = min(target_w / src_w, target_h / src_h)
            new_w = int(src_w * scale)
            new_h = int(src_h * scale)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            offset = ((target_w - new_w) // 2, (target_h - new_h) // 2)

            bg.paste(resized, offset)
            canvas = bg

        if corner_logo_path and os.path.exists(corner_logo_path):
            try:
                with Image.open(corner_logo_path) as logo:
                    if logo.mode != "RGBA":
                        logo = logo.convert("RGBA")
                    logo_h = int(logo.size[1] * (corner_logo_size / logo.size[0]))
                    logo = logo.resize((corner_logo_size, logo_h), Image.LANCZOS)
                    logo_x = target_w - corner_logo_size - corner_logo_margin
                    logo_y = corner_logo_margin
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(logo, (logo_x, logo_y), logo)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Corner logo error: {e}")

        if bottom_logo_path and os.path.exists(bottom_logo_path):
            try:
                with Image.open(bottom_logo_path) as logo:
                    if logo.mode != "RGBA":
                        logo = logo.convert("RGBA")
                    logo_w = int(logo.size[0] * (bottom_logo_height / logo.size[1]))
                    logo = logo.resize((logo_w, bottom_logo_height), Image.LANCZOS)
                    logo_x = (target_w - logo_w) // 2
                    logo_y = target_h - bottom_logo_height - bottom_logo_margin
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(logo, (logo_x, logo_y), logo)
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Bottom logo error: {e}")

        if overlay_template_path and os.path.exists(overlay_template_path):
            try:
                with Image.open(overlay_template_path) as overlay:
                    if overlay.mode != "RGBA":
                        overlay = overlay.convert("RGBA")
                    overlay = overlay.resize((target_w, target_h), Image.LANCZOS)
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.alpha_composite(overlay, dest=(0, 0))
                    canvas = canvas_rgba.convert("RGB")
            except Exception as e:
                print(f"[WARN] Overlay error: {e}")

        canvas.save(output_path, format="JPEG", quality=92, subsampling=2)
        return os.path.abspath(output_path)

    except Exception as e:
        print(f"[ERROR] Could not create carousel secondary ({image_path}): {e}")
        return None
