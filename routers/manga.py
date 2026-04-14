import os
import io
import json
import base64
import math
import logging
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types as genai_types

manga_bp = Blueprint('manga', __name__)
logger = logging.getLogger(__name__)

def _get_client():
    apiKey = os.environ.get("GEMINI_API_KEY", "")
    try:
        return genai.Client(api_key=apiKey, http_options={'api_version': 'v1alpha'})
    except Exception as e:
        logger.warning(f"GenAI Client Init Failed: {e}")
        return None

# Configuration
GEMINI_TEXT_MODEL = "gemini-2.0-flash-exp" # Using latest stable
IMAGEN_MODEL = "imagen-3.0-generate-001"   # Updated for production

# Utility: Copyright Check (Placeholder for real implementation)
def check_copyright(text):
    ng_words = ["disney", "nintendo", "mickey", "mario", "pikachu", "dragon ball", "one piece"]
    text_low = text.lower()
    for w in ng_words:
        if w in text_low:
            return w
    return None

def get_style_prompt(style_name):
    styles = {
        "少年漫画風（ダイナミック）": "dynamic shonen manga style, sharp ink lines, dramatic shading, high contrast",
        "少女漫画風（美麗）": "elegant shoujo manga style, soft lines, sparkly eyes, decorative screentones",
        "デジタルイラスト風": "modern digital illustration style, vibrant colors, clean vector lines, professional cel shading",
        "劇画風（シリアス）": "classic gekiga style, heavy ink work, realistic anatomy, gritty texture",
        "モノクロ線画": "clean black and white line art, G-pen style, no tones",
    }
    return styles.get(style_name, styles["少年漫画風（ダイナミック）"])

# Utility: Font Loading
def _load_font(size, name="gothic"):
    try:
        font_paths = {
            "gothic": "/System/Library/Fonts/jp/ヒラギノ角ゴシック W6.ttc",
            "mincho": "/System/Library/Fonts/jp/ヒラギノ明朝 ProN.ttc",
            "maru": "/Library/Fonts/Arial Unicode.ttf" # Fallback
        }
        return ImageFont.truetype(font_paths.get(name, font_paths["gothic"]), size)
    except:
        return ImageFont.load_default()

def _wrap_text(text, font, max_width):
    lines = []
    if not text: return lines
    words = list(text) # Char based for Japanese
    current_line = ""
    for char in words:
        test_line = current_line + char
        w = font.getlength(test_line)
        if w <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = char
    lines.append(current_line)
    return lines

def add_speech_bubble(image_bytes, dialogue, bubble_style="rounded", font_name="gothic"):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size
    
    bubble_w = int(w * 0.75)
    font_size = max(20, int(h * 0.04))
    font = _load_font(font_size, font_name)
    padding = font_size
    lines = _wrap_text(dialogue, font, bubble_w - padding * 2)
    
    line_h = font_size + 8
    bubble_h = line_h * len(lines) + padding * 2
    
    bx = w - bubble_w - 20
    by = 20
    
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Draw Bubble
    fill = (255, 255, 255, 235)
    outline = (0, 0, 0, 255)
    draw.rounded_rectangle([bx, by, bx + bubble_w, by + bubble_h], radius=20, fill=fill, outline=outline, width=3)
    
    # Text
    for i, line in enumerate(lines):
        draw.text((bx + padding, by + padding + i * line_h), line, font=font, fill=(0, 0, 0, 255))
        
    img = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

@manga_bp.route("/story", methods=["POST"])
def generate_story():
    data = request.get_json()
    all_input = " ".join([data.get("genre", ""), data.get("theme", ""), data.get("char_name", "")])
    ng = check_copyright(all_input)
    if ng: return jsonify({"error": f"Copyright restriction: {ng}"}), 400

    prompt = f"""Generate a professional manga plot based on:
Genre: {data.get('genre')}
Theme: {data.get('theme')}
Target User Input: Name={data.get('char_name')}, Desc={data.get('char_appearance')}
Output JSON: {{ "plot": {{ "ki": "...", "sho": "...", "ten": "...", "ketsu": "..." }}, "visual_tags": "...", "title": "..." }}
"""
    client = _get_client()
    if not client: return jsonify({"error": "Gemini Client not initialized. Check API Key."}), 500
    resp = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt, config=genai_types.GenerateContentConfig(response_mime_type="application/json"))
    return jsonify(resp.parsed)

@manga_bp.route("/panels", methods=["POST"])
def generate_panels():
    data = request.get_json()
    prompt = f"Convert this script into 4-6 manga panels (JSON): {data.get('script')}"
    client = _get_client()
    if not client: return jsonify({"error": "Gemini Client not initialized. Check API Key."}), 500
    resp = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt, config=genai_types.GenerateContentConfig(response_mime_type="application/json"))
    return jsonify({"panels": resp.parsed})

@manga_bp.route("/generate-image", methods=["POST"])
def generate_image():
    data = request.get_json()
    prompt = f"{data.get('subject')}, {data.get('action')}, {data.get('background')}, {get_style_prompt(data.get('art_style'))}"
    
    client = _get_client()
    if not client: return jsonify({"error": "Gemini Client not initialized. Check API Key."}), 500
    resp = client.models.generate_images(
        model=IMAGEN_MODEL,
        prompt=prompt,
        config=genai_types.GenerateImagesConfig(number_of_images=1, aspect_ratio="3:4")
    )
    
    img_bytes = resp.generated_images[0].image.image_bytes
    if data.get("dialogue"):
        img_bytes = add_speech_bubble(img_bytes, data.get("dialogue"), data.get("bubble_style"), data.get("font_name"))
        
    b64 = base64.b64encode(img_bytes).decode('utf-8')
    return jsonify({"images": [f"data:image/png;base64,{b64}"], "prompt_used": prompt})
