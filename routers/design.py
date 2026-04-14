import io
import os
import json
import base64
import re
import traceback
import tempfile
import math
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context

logger = logging.getLogger(__name__)
from werkzeug.utils import secure_filename
from PIL import Image, ImageEnhance
from google.genai import types as genai_types

# Late import to avoid issues if not installed
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

design_bp = Blueprint('design', __name__)

# --- Config & Prompts ---
GEMINI_TEXT_MODEL = "gemini-2.5-flash"

PROMPT_ENRICH = """
You are a layout analysis expert. I have extracted structural elements (TEXT/IMAGES/VECTORS) from a PDF page.
Task: Assign SEMANTIC ROLES and SPATIAL RELATIONSHIPS to each element.
Output JSON array — one object per element:
[{{
  "id": "element_id",
  "role": "headline" | "body" | "caption" | "decoration" | "frame" | "photo" | "logo" | "subheadline",
  "is_template_placeholder": bool,
  "suggested_name": "descriptive name string",
  "group_id": "integer",
  "adjacent_ids": ["id1", "id2"]
}}]
Elements to analyze: {elements_json}
"""

PROMPT_OCR_ASSETS = """
Perform FULL OCR AND PRECISE ASSET DETECTION. Output a JSON array of objects:
{{
  "type": "text" | "image",
  "content": "string",
  "x": number, "y": number, "w": number, "h": number,
  "font_size": number, "color": "#rrggbb",
  "role": "headline" | "subheadline" | "body" | "caption" | "photo" | "logo" | "decoration",
  "z_index": number, "group_id": number,
  "is_template_placeholder": true,
  "suggested_name": "string"
}}
Page coordinate system: 420x297 mm.
"""

PROMPT_IMG_TRANSFORM = """Analyze the instruction "{prompt}" and return JSON transform parameters (0.0 to 2.0)."""

PROMPT_LAYOUT = """Suggest layout improvements for A3 (420x297mm). User request: "{prompt}". Elements: {elements_json}"""

PROMPT_MAGAZINE_SCAN = """
あなたは日本語の広報誌・雑誌デザインの専門家です。
このページ画像を精密に分析し、以下の厳密なJSONスキーマで出力してください。

{{
  "page_type": "cover" | "recipe" | "interview" | "service_overview" | "staff_feature" | "announcement" | "general",
  "design_spec": {{
    "color_palette": [
      {{"hex": "#RRGGBB", "role": "primary" | "accent" | "bg" | "text" | "section_bg", "usage": "用途の説明"}}
    ],
    "typography": [
      {{"role": "headline" | "subheadline" | "body" | "caption" | "logo", "estimated_size_pt": number, "weight": "bold" | "regular" | "light", "direction": "vertical" | "horizontal", "style": "gothic" | "mincho" | "decorative"}}
    ],
    "layout_grid": {{
      "columns": number,
      "gutter_mm": number,
      "margin": {{"top": number, "right": number, "bottom": number, "left": number}}
    }},
    "spacing_pattern": "tight" | "balanced" | "airy"
  }},
  "zones": [
    {{
      "id": "zone_0",
      "role": "headline" | "subheadline" | "photo" | "body" | "recipe_steps" | "qa_block" | "category_card" | "accent_bar" | "logo" | "page_number" | "decoration" | "sidebar",
      "bounds": {{"x_mm": number, "y_mm": number, "w_mm": number, "h_mm": number}},
      "text_content": "読み取れるテキスト内容（なければ空文字）",
      "text_direction": "vertical" | "horizontal",
      "bg_color": "#RRGGBB または null",
      "fg_color": "#RRGGBB",
      "font_size_pt": number,
      "font_weight": "bold" | "regular" | "light",
      "is_editable": true,
      "z_order": number
    }}
  ]
}}

分析ルール:
- 座標系はA3見開き: 幅420mm × 高さ297mm（左上が原点）
- 縦書き（tategaki）テキストを正確に検出し、text_direction: "vertical" で出力
- ルビ（ふりがな）は本文に含めて出力（括弧表記可）
- 写真・イラスト領域はrole: "photo"で、内容の簡潔な説明をtext_contentに入れる
- 色付きの背景帯・セクション分けはrole: "accent_bar" or "sidebar"で検出
- ページ番号やフッター情報も検出する
- color_paletteは実際にページで使われている色を5〜8色抽出
- zones は重要な要素を15〜30個程度検出（多すぎず少なすぎず）
- 座標は整数mmで十分（小数点以下不要）
"""

# --- Helpers ---
def _get_gemini_client():
    from google import genai
    from pathlib import Path
    apiKey = os.environ.get("GEMINI_API_KEY", "")
    if not apiKey:
        env_file = Path.home() / ".secretary" / "tools" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and line.startswith('GEMINI_API_KEY='):
                    apiKey = line.split('=', 1)[1].strip()
                    break
    try:
        return genai.Client(api_key=apiKey, http_options={'api_version': 'v1alpha'})
    except Exception as e:
        logger.warning(f"Gemini Client Init Failed: {e}")
        return None

def _al_get_gen_config():
    from google.genai import types as genai_types
    return genai_types.GenerationConfig(
        temperature=0.0,
        response_mime_type="application/json",
        max_output_tokens=8192
    )

def _al_clean_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text).strip()
    if text.startswith('[') and not text.endswith(']'):
        last = text.rfind('}')
        if last != -1: text = text[:last+1] + ']'
    return text

def _al_rgb_to_hex(rgb):
    if not rgb or len(rgb) != 3: return "#000000"
    return "#{:02x}{:02x}{:02x}".format(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

def _al_group_text_spans(text_dict, scale_x, scale_y):
    textblocks = []
    for block in text_dict["blocks"]:
        if "lines" not in block: continue
        spans_in_block = []
        for line in block["lines"]:
            for span in line["spans"]:
                content = span["text"].strip()
                if not content: continue
                bbox = span["bbox"]
                spans_in_block.append({
                    "text": content,
                    "x": bbox[0] * scale_x, "y": bbox[1] * scale_y,
                    "w": (bbox[2] - bbox[0]) * scale_x, "h": (bbox[3] - bbox[1]) * scale_y,
                    "font_size": span["size"],
                    "color": "#{:06x}".format(span["color"]) if "color" in span else "#000000"
                })
        if not spans_in_block: continue
        bx, by = min(s["x"] for s in spans_in_block), min(s["y"] for s in spans_in_block)
        bx2, by2 = max(s["x"] + s["w"] for s in spans_in_block), max(s["y"] + s["h"] for s in spans_in_block)
        textblocks.append({
            "type": "textblock", "x": bx, "y": by, "w": bx2 - bx, "h": by2 - by,
            "spans": spans_in_block, "font_size": max(s["font_size"] for s in spans_in_block),
        })
    return textblocks

def _al_get_page_structure(page):
    rect = page.rect
    w_orig, h_orig = rect.width, rect.height
    scale_x, scale_y = 420.0 / w_orig, 297.0 / h_orig
    structure = []
    text_dict = page.get_text("dict")
    for tb in _al_group_text_spans(text_dict, scale_x, scale_y):
        tb["id"] = f"textblock_{len(structure)}"
        tb["_scale_y"] = scale_y
        structure.append(tb)
    
    img_list = page.get_images(full=True)
    for img in img_list:
        xref = img[0]
        try:
            base_image = page.parent.extract_image(xref)
            insts = page.get_image_rects(xref)
            for i, r in enumerate(insts):
                structure.append({
                    "id": f"img_{xref}_{i}", "type": "image",
                    "x": r.x0*scale_x, "y": r.y0*scale_y, "w": (r.x1-r.x0)*scale_x, "h": (r.y1-r.y0)*scale_y,
                    "base64": base64.b64encode(base_image["image"]).decode('utf-8'), "ext": base_image["ext"]
                })
        except: pass

    drawings = page.get_drawings()
    for d in drawings:
        if not d.get("rect"): continue
        r = d["rect"]
        if r.width < 1 or r.height < 1: continue
        structure.append({
            "id": f"vec_{len(structure)}", "type": "rect",
            "x": r.x0*scale_x, "y": r.y0*scale_y, "w": (r.x1-r.x0)*scale_x, "h": (r.y1-r.y0)*scale_y,
            "fill": _al_rgb_to_hex(d["fill"]) if d.get("fill") else "none",
            "stroke": _al_rgb_to_hex(d["color"]) if d.get("color") else "none",
            "stroke_width": d.get("width", 1)*scale_x
        })
    return structure, scale_y

def _al_process_page_hybrid(page, page_num):
    client = _get_gemini_client()
    pix = page.get_pixmap(dpi=300)
    img_pil = Image.open(io.BytesIO(pix.tobytes("png")))
    img_w, img_h = img_pil.size
    encoded_image = base64.b64encode(pix.tobytes("png")).decode('utf-8')
    structure, scale_y = _al_get_page_structure(page)
    native_texts = [s for s in structure if s["type"] in ("text", "textblock")]

    if len(native_texts) < 3:
        contents = [{"mime_type": "image/png", "data": encoded_image}, PROMPT_OCR_ASSETS]
        try:
            response = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=contents, generation_config=_al_get_gen_config())
            ai_elements = json.loads(_al_clean_json(response.text))
            final_structure = []
            for i, el in enumerate(ai_elements):
                if el.get("type") == "image":
                    cx, cy = int((el["x"] / 420.0) * img_w), int((el["y"] / 297.0) * img_h)
                    cw, ch = int((el["w"] / 420.0) * img_w), int((el["h"] / 297.0) * img_h)
                    if cw > 0 and ch > 0:
                        cropped = img_pil.crop((cx, cy, cx+cw, cy+ch))
                        buf = io.BytesIO()
                        cropped.save(buf, format="PNG")
                        el["base64"] = base64.b64encode(buf.getvalue()).decode('utf-8')
                        el["ext"] = "png"
                el["id"] = f"ai_{i}"
                el["is_placeholder"] = el.pop("is_template_placeholder", False)
                el["label"] = el.pop("suggested_name", "")
                final_structure.append(el)
            return final_structure
        except: return structure
    else:
        gemini_input = [{"id": s["id"], "type": s["type"], "x": round(s["x"], 1), "y": round(s["y"], 1), "content": s.get("content", "")[:30]} for s in structure[:150]]
        contents = [{"mime_type": "image/png", "data": encoded_image}, PROMPT_ENRICH.format(elements_json=json.dumps(gemini_input, ensure_ascii=False))]
        try:
            response = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=contents, generation_config=_al_get_gen_config())
            labels = json.loads(_al_clean_json(response.text))
            l_map = {l["id"]: l for l in labels if isinstance(l, dict) and "id" in l}
            for s in structure:
                l = l_map.get(s["id"], {})
                s.update({"role": l.get("role", "decoration"), "is_placeholder": l.get("is_template_placeholder", False),
                          "label": l.get("suggested_name", ""), "group_id": l.get("group_id", 0), "adjacent_ids": l.get("adjacent_ids", [])})
        except: pass
        return structure

def _al_build_svg(structure):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297" data-template="true">\n'
    svg += '  <defs><style>.element { cursor: grab; } .element:active { cursor: grabbing; } .ph { outline: 2px dashed #00f0ff; }</style></defs>\n'
    svg += '  <rect width="420" height="297" fill="#F8F8F8" id="bg-rect"/>\n'
    for i, s in enumerate(sorted(structure, key=lambda s: s.get("z_index", 0))):
        x, y, w, h = round(s["x"], 2), round(s["y"], 2), round(s["w"], 2), round(s["h"], 2)
        is_ph, label, role, group_id = s.get("is_placeholder", False), s.get("label", "").replace('"', '&quot;'), s.get("role", "decoration"), s.get("group_id", "")
        ph_class, gid = " ph" if is_ph else "", f"el_{i}"
        g_open = f'  <g id="{gid}" class="element selectable{ph_class}" data-id="{gid}" data-role="{role}" data-type="{s["type"]}" data-group="{group_id}" data-label="{label}">\n'
        if s["type"] == "textblock":
            svg += g_open
            block_scale_y = s.get("_scale_y", 297.0 / 842.0)
            for j, span in enumerate(s.get("spans", [])):
                fs, content = max(round(span["font_size"] * block_scale_y, 2), 1.5), str(span["text"]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                svg += f'    <text x="{round(span["x"], 2)}" y="{round(span["y"] + span["h"] * 0.85, 2)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs}" fill="{span["color"]}" data-span-id="{j}">{content}</text>\n'
            svg += '  </g>\n'
        elif s["type"] == "text":
            svg += g_open
            fs, content = max(round(float(s.get("font_size", 0)), 2) if s.get("font_size", 0) > 0 else round(h * 0.7, 2), 1.5), str(s.get("content", "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            svg += f'    <text x="{x}" y="{round(y + h * 0.85, 2)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs}" fill="{s.get("color", "#000000")}">{content}</text>\n'
            svg += '  </g>\n'
        elif s["type"] == "image":
            svg += g_open + f'    <image x="{x}" y="{y}" width="{w}" height="{h}" href="data:image/{s.get("ext","png")};base64,{s.get("base64","")}"/>\n  </g>\n'
        elif s["type"] == "rect":
            svg += g_open + f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{s.get("fill","none")}" stroke="{s.get("stroke","none")}" stroke-width="{s.get("stroke_width", 1)}"/>\n  </g>\n'
    return svg + '</svg>'

# --- Magazine Scan Pipeline ---
def _scan_page_magazine(page, page_num):
    """High-fidelity magazine page analysis using Gemini Vision."""
    client = _get_gemini_client()
    if not client:
        logger.error(f"Magazine scan page {page_num}: Gemini client is None, falling back")
        return None, None
    logger.info(f"Magazine scan page {page_num}: client OK, starting analysis")

    # 300 DPI for AI analysis
    pix_hi = page.get_pixmap(dpi=300)

    # 72 DPI JPEG for ghost reference background (compact payload)
    pix_lo = page.get_pixmap(dpi=72)
    img_lo = Image.open(io.BytesIO(pix_lo.tobytes("png")))
    buf_lo = io.BytesIO()
    img_lo.save(buf_lo, format="JPEG", quality=50)
    encoded_lo = base64.b64encode(buf_lo.getvalue()).decode('utf-8')

    try:
        response = client.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=[
                genai_types.Part.from_bytes(data=pix_hi.tobytes("png"), mime_type="image/png"),
                PROMPT_MAGAZINE_SCAN
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                max_output_tokens=32768
            )
        )
        scan_result = json.loads(_al_clean_json(response.text))
        logger.info(f"Page {page_num} scan: type={scan_result.get('page_type')}, zones={len(scan_result.get('zones', []))}")
    except Exception as e:
        logger.error(f"Magazine scan page {page_num} failed: {e}")
        scan_result = {
            "page_type": "general",
            "design_spec": {"color_palette": [], "typography": [], "layout_grid": {"columns": 2, "gutter_mm": 5, "margin": {"top": 15, "right": 10, "bottom": 15, "left": 10}}, "spacing_pattern": "balanced"},
            "zones": []
        }

    return scan_result, encoded_lo


def _build_layered_svg(scan_result, bg_image_b64):
    """Build a layered SVG with ghost reference background and editable overlay zones."""
    page_type = scan_result.get("page_type", "general")
    zones = scan_result.get("zones", [])

    svg = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="420mm" height="297mm" viewBox="0 0 420 297" data-template="true" data-page-type="' + page_type + '">\n'
    svg += '  <defs><style>\n'
    svg += '    .element { cursor: grab; } .element:active { cursor: grabbing; }\n'
    svg += '    .ph { outline: 2px dashed #00f0ff; }\n'
    svg += '    .ghost-ref { pointer-events: none; }\n'
    svg += '    .zone-overlay { pointer-events: all; }\n'
    svg += '  </style></defs>\n'

    # Layer 1: Ghost reference background
    svg += f'  <g id="ghost-layer" class="ghost-ref" opacity="0.12">\n'
    svg += f'    <image x="0" y="0" width="420" height="297" href="data:image/jpeg;base64,{bg_image_b64}"/>\n'
    svg += '  </g>\n'

    # Layer 2: Background zone rects (accent bars, section backgrounds)
    bg_roles = {"accent_bar", "sidebar", "category_card", "section_bg"}
    svg += '  <g id="bg-zones-layer">\n'
    for z in sorted(zones, key=lambda z: z.get("z_order", 0)):
        if z.get("role") in bg_roles and z.get("bg_color"):
            b = z.get("bounds", {})
            x, y, w, h = b.get("x_mm", 0), b.get("y_mm", 0), b.get("w_mm", 50), b.get("h_mm", 20)
            zid = z.get("id", "zone")
            role = z.get("role", "decoration")
            label = z.get("text_content", "")[:30].replace('"', '&quot;')
            svg += f'    <g id="{zid}" class="element selectable zone-overlay" data-id="{zid}" data-role="{role}" data-type="rect" data-zone-id="{zid}" data-label="{label}">\n'
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{z["bg_color"]}" opacity="0.7"/>\n'
            svg += '    </g>\n'
    svg += '  </g>\n'

    # Layer 3: Editable text and photo placeholder zones
    svg += '  <g id="content-layer">\n'
    for z in sorted(zones, key=lambda z: z.get("z_order", 0)):
        if z.get("role") in bg_roles and z.get("bg_color"):
            continue  # already rendered in layer 2

        b = z.get("bounds", {})
        x, y, w, h = b.get("x_mm", 0), b.get("y_mm", 0), b.get("w_mm", 50), b.get("h_mm", 20)
        zid = z.get("id", "zone")
        role = z.get("role", "decoration")
        text = z.get("text_content", "")
        label = text[:30].replace('"', '&quot;') if text else role
        direction = z.get("text_direction", "horizontal")
        fg = z.get("fg_color", "#000000")
        fs_pt = z.get("font_size_pt", 10)
        fs_mm = max(round(fs_pt * 0.352778, 2), 1.5)
        fw = "bold" if z.get("font_weight") == "bold" else "normal"

        svg += f'    <g id="{zid}" class="element selectable zone-overlay ph" data-id="{zid}" data-role="{role}" data-type="{"textblock" if text else "rect"}" data-zone-id="{zid}" data-label="{label}" data-direction="{direction}">\n'

        if role == "photo":
            # Photo placeholder with description
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#E0E0E0" stroke="#999" stroke-width="0.5" stroke-dasharray="2,2"/>\n'
            desc = text[:20] if text else "photo"
            svg += f'      <text x="{x + w/2}" y="{y + h/2}" font-family="YuGothic, sans-serif" font-size="4" fill="#666" text-anchor="middle" dominant-baseline="middle">[{desc}]</text>\n'
        elif text:
            # Editable text zone
            if direction == "vertical":
                # Vertical text: render top-to-bottom, right-to-left columns
                col_x = x + w - fs_mm * 1.2
                char_y = y + fs_mm
                for char in text[:100]:
                    if char == '\n' or char_y > y + h - fs_mm:
                        col_x -= fs_mm * 1.5
                        char_y = y + fs_mm
                        if col_x < x:
                            break
                    if char != '\n':
                        svg += f'      <text x="{round(col_x, 1)}" y="{round(char_y, 1)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs_mm}" font-weight="{fw}" fill="{fg}" text-anchor="middle">{char}</text>\n'
                        char_y += fs_mm * 1.3
            else:
                # Horizontal text with line wrapping
                lines = text.split('\n') if '\n' in text else [text]
                line_h = fs_mm * 1.6
                ty = y + fs_mm
                for line in lines[:20]:
                    if ty > y + h:
                        break
                    safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    svg += f'      <text x="{x}" y="{round(ty, 1)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs_mm}" font-weight="{fw}" fill="{fg}">{safe}</text>\n'
                    ty += line_h
        else:
            # Empty zone placeholder
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#00f0ff" stroke-width="0.3" stroke-dasharray="2,1"/>\n'

        svg += '    </g>\n'
    svg += '  </g>\n'

    return svg + '</svg>'

# --- Routes ---
@design_bp.route("/transform-image", methods=["POST"])
def analyze_style():
    client = _get_gemini_client()
    data = request.get_json()
    image_data = data.get("image")
    if not image_data: return jsonify({"error": "image is required"}), 400
    if "," in image_data: header, b64 = image_data.split(",", 1); media_type = header.split(";")[0].split(":")[1]
    else: b64, media_type = image_data, "image/jpeg"
    image_bytes = base64.b64decode(b64)
    response = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=[genai_types.Part.from_bytes(data=image_bytes, mime_type=media_type), "分析、JSON出力: {style_prompt, style_label, description}"])
    return jsonify(json.loads(_al_clean_json(response.text)))

@design_bp.route('/convert-pdf', methods=['POST'])
def convert_pdf():
    if fitz is None: return jsonify({'error': 'PyMuPDF missing'}), 500
    file = request.files.get('pdf')
    if not file: return jsonify({'error': 'No file'}), 400
    temp_path = os.path.join('/tmp', secure_filename(file.filename) or 'upload.pdf')
    file.save(temp_path)
    def generate():
        try:
            doc = fitz.open(temp_path)
            total = len(doc)
            yield 'data: ' + json.dumps({"status": "start", "total": total}) + '\n\n'
            pages = []
            for i in range(total):
                yield 'data: ' + json.dumps({"status": "progress", "page": i+1, "total": total, "message": f"Analyzing Page {i+1}..."}) + '\n\n'
                pages.append(_al_build_svg(_al_process_page_hybrid(doc[i], i+1)))
            yield 'data: ' + json.dumps({"status": "complete", "pages": pages}) + '\n\n'
        except Exception: yield 'data: ' + json.dumps({"status": "error", "message": traceback.format_exc()}) + '\n\n'
        finally:
            if os.path.exists(temp_path): os.remove(temp_path)
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@design_bp.route('/project-load', methods=['POST'])
def project_load():
    """
    Directly load a PDF file from the project root (Demo/Efficiency mode).
    """
    if fitz is None: return jsonify({'error': 'PyMuPDF missing'}), 500
    data = request.json or {}
    filename = data.get('filename')
    if not filename: return jsonify({'error': 'No filename'}), 400
    
    target_path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(target_path):
        return jsonify({'error': f'File {filename} not found in project root.'}), 404

    def generate():
        try:
            doc = fitz.open(target_path)
            total = len(doc)
            yield 'data: ' + json.dumps({"status": "start", "total": total}) + '\n\n'
            pages = []
            for i in range(total):
                yield 'data: ' + json.dumps({"status": "progress", "page": i+1, "total": total, "message": f"Analyzing Page {i+1}..."}) + '\n\n'
                pages.append(_al_build_svg(_al_process_page_hybrid(doc[i], i+1)))
            yield 'data: ' + json.dumps({"status": "complete", "pages": pages}) + '\n\n'
        except Exception: yield 'data: ' + json.dumps({"status": "error", "message": traceback.format_exc()}) + '\n\n'
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


SCAN_RESULTS_DIR = '/tmp/ai-creator-scans'
os.makedirs(SCAN_RESULTS_DIR, exist_ok=True)


# =====================================================
# Designer-First Pipeline: Preview → Design System → Templatize
# =====================================================

@design_bp.route('/preview-pdf', methods=['POST'])
def preview_pdf():
    """Phase 1: Instant PDF preview — no AI, <1 second. Renders all pages as JPEGs."""
    if fitz is None:
        return jsonify({'error': 'PyMuPDF missing'}), 500
    file = request.files.get('pdf')
    if not file:
        return jsonify({'error': 'No file'}), 400

    import time as _time
    scan_id = f"scan_{int(_time.time())}"
    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    os.makedirs(scan_dir, exist_ok=True)

    temp_path = os.path.join('/tmp', secure_filename(file.filename) or 'preview.pdf')
    file.save(temp_path)

    try:
        doc = fitz.open(temp_path)
        total = len(doc)
        pages = []
        for i in range(total):
            pix = doc[i].get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            jpg_path = os.path.join(scan_dir, f"preview_{i + 1}.jpg")
            img.save(jpg_path, format="JPEG", quality=80)
            pages.append({"page": i + 1, "preview_url": f"/api/design/preview/{scan_id}/{i + 1}"})

        # Save PDF path for later templatize use
        import shutil
        pdf_copy = os.path.join(scan_dir, "source.pdf")
        shutil.copy2(temp_path, pdf_copy)

        return jsonify({"scan_id": scan_id, "total_pages": total, "pages": pages})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@design_bp.route('/preview/<scan_id>/<int:page_num>', methods=['GET'])
def get_preview(scan_id, page_num):
    """Serve page preview JPEG."""
    from flask import send_file
    img_path = os.path.join(SCAN_RESULTS_DIR, scan_id, f"preview_{page_num}.jpg")
    if not os.path.exists(img_path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(img_path, mimetype='image/jpeg')


PROMPT_DESIGN_SYSTEM = """
この雑誌の複数ページを分析し、全体のデザインシステムを抽出してください。
厳密なJSONで出力:
{{
  "brand_colors": [
    {{"hex": "#RRGGBB", "name": "カラー名", "role": "primary|accent|bg|text|section_bg", "usage": "用途説明"}}
  ],
  "typography": [
    {{"role": "大見出し|中見出し|本文|キャプション|ロゴ", "estimated_size_pt": number, "weight": "bold|regular|light", "style": "gothic|mincho|decorative", "direction": "horizontal|vertical"}}
  ],
  "layout_patterns": [
    {{"name": "パターン名（例:レシピページ）", "columns": number, "description": "構成の説明"}}
  ],
  "page_types": ["cover", "recipe", "interview", "info", "staff", "announcement"],
  "overall_mood": "warm|cool|modern|traditional|playful|professional"
}}
brand_colorsは実際に使われている色を6〜10色抽出。
typographyは役割ごとに異なるスタイルを4〜6種。
layout_patternsはページ構成パターンを3〜5種。
"""


@design_bp.route('/extract-design-system/<scan_id>', methods=['POST'])
def extract_design_system(scan_id):
    """Phase 2: Extract design system from representative pages (1 AI call)."""
    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    pdf_path = os.path.join(scan_dir, "source.pdf")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'Scan not found'}), 404

    import requests as _req

    api_key = _get_openrouter_key()
    if not api_key:
        return jsonify({'error': 'OPENROUTER_API_KEY not found'}), 500

    doc = fitz.open(pdf_path)
    total = len(doc)

    # Pick 3 representative pages: first, middle, last
    indices = [0]
    if total > 2:
        indices.append(total // 2)
    if total > 1:
        indices.append(total - 1)

    # Render at 50 DPI (small thumbnails for cost efficiency)
    image_parts = []
    for idx in indices:
        pix = doc[idx].get_pixmap(dpi=50)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        image_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    image_parts.append({"type": "text", "text": PROMPT_DESIGN_SYSTEM})

    for model in VISION_MODELS:
        try:
            resp = _req.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "temperature": 0.0,
                    "messages": [{"role": "user", "content": image_parts}]
                },
                timeout=60
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            result = json.loads(_al_clean_json(raw))

            # Save design system
            with open(os.path.join(scan_dir, "design_system.json"), 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False)

            logger.info(f"Design system [{model}]: {len(result.get('brand_colors', []))} colors, {len(result.get('typography', []))} typo")
            return jsonify({"design_system": result, "model_used": model})
        except Exception as e:
            logger.warning(f"Design system [{model}] failed: {e}")
            continue

    return jsonify({'error': 'All models failed'}), 500


@design_bp.route('/templatize/<scan_id>/<int:page_num>', methods=['POST'])
def templatize_page(scan_id, page_num):
    """Phase 3: Convert a single page to editable SVG template (on-demand)."""
    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    pdf_path = os.path.join(scan_dir, "source.pdf")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'Scan not found'}), 404

    doc = fitz.open(pdf_path)
    if page_num < 1 or page_num > len(doc):
        return jsonify({'error': f'Page {page_num} out of range'}), 400

    page = doc[page_num - 1]

    # Generate high-quality ghost reference (150 DPI)
    pix_ghost = page.get_pixmap(dpi=150)
    img_ghost = Image.open(io.BytesIO(pix_ghost.tobytes("png")))
    ghost_path = os.path.join(scan_dir, f"ghost_{page_num}.jpg")
    img_ghost.save(ghost_path, format="JPEG", quality=80)

    # AI Vision analysis for this page
    scan_result = _scan_page_qwen_vl(page, page_num)

    # Save spec
    spec_path = os.path.join(scan_dir, f"spec_{page_num}.json")
    with open(spec_path, 'w', encoding='utf-8') as f:
        json.dump(scan_result, f, ensure_ascii=False)

    # Build SVG with URL-referenced ghost image
    ghost_url = f"/api/design/ghost-image/{scan_id}/{page_num}"
    svg = _build_layered_svg_url(scan_result, ghost_url)

    return jsonify({"svg": svg, "spec": scan_result, "ghost_url": ghost_url})


@design_bp.route('/scan-pdf', methods=['POST'])
def scan_pdf():
    """Step 1: Scan PDF pages with Gemini Vision → save results to disk. SSE sends only progress (lightweight)."""
    if fitz is None:
        return jsonify({'error': 'PyMuPDF missing'}), 500

    file = request.files.get('pdf')
    if not file:
        return jsonify({'error': 'No file'}), 400

    import time as _time
    scan_id = f"scan_{int(_time.time())}"
    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    os.makedirs(scan_dir, exist_ok=True)

    temp_path = os.path.join('/tmp', secure_filename(file.filename) or 'scan_upload.pdf')
    file.save(temp_path)

    def generate():
        try:
            doc = fitz.open(temp_path)
            total = len(doc)
            yield 'data: ' + json.dumps({"status": "start", "total": total, "scan_id": scan_id}) + '\n\n'

            all_specs = []
            for i in range(total):
                yield 'data: ' + json.dumps({"status": "progress", "page": i + 1, "total": total, "message": f"AI Vision分析中... Page {i + 1}/{total}"}) + '\n\n'

                # Save ghost image as separate JPEG file
                pix_lo = doc[i].get_pixmap(dpi=72)
                img_lo = Image.open(io.BytesIO(pix_lo.tobytes("png")))
                ghost_path = os.path.join(scan_dir, f"ghost_{i + 1}.jpg")
                img_lo.save(ghost_path, format="JPEG", quality=50)

                # Qwen2.5-VL Vision analysis via OpenRouter
                scan_result = _scan_page_qwen_vl(doc[i], i + 1)

                # Save spec JSON per page
                spec_path = os.path.join(scan_dir, f"spec_{i + 1}.json")
                with open(spec_path, 'w', encoding='utf-8') as f:
                    json.dump(scan_result, f, ensure_ascii=False)

                all_specs.append(scan_result)

            # Merge design specs
            merged_palette = {}
            merged_typography = []
            page_types = []
            for spec in all_specs:
                page_types.append(spec.get("page_type", "general"))
                for c in spec.get("design_spec", {}).get("color_palette", []):
                    h = c.get("hex", "").upper()
                    if h and h not in merged_palette:
                        merged_palette[h] = c
                for t in spec.get("design_spec", {}).get("typography", []):
                    merged_typography.append(t)

            summary = {
                "scan_id": scan_id,
                "total_pages": total,
                "page_types": page_types,
                "design_spec": {
                    "color_palette": list(merged_palette.values()),
                    "typography": merged_typography,
                }
            }
            with open(os.path.join(scan_dir, "summary.json"), 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False)

            yield 'data: ' + json.dumps({"status": "complete", **summary}, ensure_ascii=False) + '\n\n'

        except Exception:
            yield 'data: ' + json.dumps({"status": "error", "message": traceback.format_exc()}) + '\n\n'
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@design_bp.route('/export-idml/<scan_id>', methods=['GET'])
def export_idml(scan_id):
    """Convert all spec_*.json files for a scan into an IDML file and return it."""
    import sys
    import glob as _glob
    from flask import send_file

    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    if not os.path.exists(scan_dir):
        return jsonify({'error': 'Scan not found'}), 404

    spec_files = sorted(_glob.glob(os.path.join(scan_dir, 'spec_*.json')))
    if not spec_files:
        return jsonify({'error': 'No spec files found'}), 404

    # Convert specs to the layouts format expected by build_dynamic_idml
    layouts = []
    for spec_path in spec_files:
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec = json.load(f)

        page_num = int(os.path.basename(spec_path).replace('spec_', '').replace('.json', ''))
        blocks = []
        for zone in spec.get('zones', []):
            bounds = zone.get('bounds', {})
            font_size = zone.get('font_size_pt', 12)
            block = {
                'type': 'text' if zone.get('text_content') else 'image',
                'x_mm': bounds.get('x_mm', 0),
                'y_mm': bounds.get('y_mm', 0),
                'width_mm': bounds.get('w_mm', 50),
                'height_mm': bounds.get('h_mm', 20),
                'content': zone.get('text_content', '') or '',
                'bg_color_hex': zone.get('bg_color') or 'transparent',
                'typography': {
                    'font_size_pt': font_size,
                    'text_color_hex': zone.get('fg_color') or '#000000',
                    'font_weight': zone.get('font_weight', 'regular'),
                    'alignment': 'left',
                    'line_height_pt': font_size * 1.5,
                },
            }
            blocks.append(block)

        layouts.append({'page': page_num, 'blocks': blocks})

    # Write layouts to a temp JSON file for build_dynamic_idml
    tmp_json = os.path.join(scan_dir, '_idml_input.json')
    with open(tmp_json, 'w', encoding='utf-8') as f:
        json.dump(layouts, f, ensure_ascii=False)

    output_path = os.path.join(scan_dir, 'export.idml')

    scripts_dir = '/Users/jungosakamoto/Claude/shared/scripts'
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    import generate_detailed_idml
    generate_detailed_idml.build_dynamic_idml(tmp_json, output_path)

    return send_file(output_path, mimetype='application/octet-stream',
                     as_attachment=True, download_name=f'{scan_id}.idml')


_FALLBACK_SPEC = {"page_type": "general", "design_spec": {"color_palette": [], "typography": [], "layout_grid": {"columns": 2, "gutter_mm": 5, "margin": {"top": 15, "right": 10, "bottom": 15, "left": 10}}, "spacing_pattern": "balanced"}, "zones": []}


def _get_openrouter_key():
    from pathlib import Path
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        env_file = Path.home() / ".secretary" / "tools" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    key = line.split('=', 1)[1].strip()
                    break
    return key


VISION_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
]


def _scan_page_qwen_vl(page, page_num):
    """Run Vision analysis via OpenRouter with model fallback chain. Returns spec JSON."""
    import requests as _req

    api_key = _get_openrouter_key()
    if not api_key:
        logger.error(f"Scan page {page_num}: OPENROUTER_API_KEY not found")
        return dict(_FALLBACK_SPEC)

    pix = page.get_pixmap(dpi=100)
    img_pil = Image.open(io.BytesIO(pix.tobytes("png")))
    buf_jpg = io.BytesIO()
    img_pil.save(buf_jpg, format="JPEG", quality=75)
    img_b64 = base64.b64encode(buf_jpg.getvalue()).decode('utf-8')
    logger.info(f"Scan page {page_num}: image size {len(buf_jpg.getvalue())//1024}KB")

    for model in VISION_MODELS:
        try:
            resp = _req.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 16384,
                    "temperature": 0.0,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            {"type": "text", "text": PROMPT_MAGAZINE_SCAN}
                        ]
                    }]
                },
                timeout=120
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            result = json.loads(_al_clean_json(raw))
            logger.info(f"Scan page {page_num} [{model}]: type={result.get('page_type')}, zones={len(result.get('zones', []))}")
            return result
        except Exception as e:
            logger.warning(f"Scan page {page_num} [{model}] failed: {e}")
            continue

    logger.error(f"Scan page {page_num}: all models failed")
    return dict(_FALLBACK_SPEC)


@design_bp.route('/scan-page/<scan_id>/<int:page_num>', methods=['GET'])
def get_scan_page(scan_id, page_num):
    """Step 2: Load a single scanned page as SVG. Ghost image referenced by URL (not embedded)."""
    scan_dir = os.path.join(SCAN_RESULTS_DIR, scan_id)
    spec_path = os.path.join(scan_dir, f"spec_{page_num}.json")
    if not os.path.exists(spec_path):
        return jsonify({'error': f'Scan page {page_num} not found'}), 404

    with open(spec_path, 'r', encoding='utf-8') as f:
        scan_result = json.load(f)

    ghost_url = f"/api/design/ghost-image/{scan_id}/{page_num}"
    svg = _build_layered_svg_url(scan_result, ghost_url)
    return jsonify({"svg": svg, "spec": scan_result})


@design_bp.route('/ghost-image/<scan_id>/<int:page_num>', methods=['GET'])
def get_ghost_image(scan_id, page_num):
    """Serve ghost reference image as static JPEG."""
    from flask import send_file
    img_path = os.path.join(SCAN_RESULTS_DIR, scan_id, f"ghost_{page_num}.jpg")
    if not os.path.exists(img_path):
        return jsonify({'error': 'Image not found'}), 404
    return send_file(img_path, mimetype='image/jpeg')


@design_bp.route('/scan-summary/<scan_id>', methods=['GET'])
def get_scan_summary(scan_id):
    """Get scan summary (design spec, page types) without SVG data."""
    summary_path = os.path.join(SCAN_RESULTS_DIR, scan_id, "summary.json")
    if not os.path.exists(summary_path):
        return jsonify({'error': 'Scan not found'}), 404
    with open(summary_path, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))


def _build_layered_svg_url(scan_result, ghost_image_url):
    """Build layered SVG with ghost image referenced by URL (not base64).
    Auto-scales AI Vision coordinates to fit the 420x297 viewBox."""
    page_type = scan_result.get("page_type", "general")
    zones = scan_result.get("zones", [])

    VB_W, VB_H = 420.0, 297.0
    MARGIN = 5.0  # mm margin inside viewBox

    # Determine coordinate range from all zones to compute scale factor
    max_x, max_y = VB_W, VB_H
    for z in zones:
        b = z.get("bounds", {})
        zx = b.get("x_mm", 0) + b.get("w_mm", 0)
        zy = b.get("y_mm", 0) + b.get("h_mm", 0)
        if zx > max_x: max_x = zx
        if zy > max_y: max_y = zy

    # If coordinates exceed viewBox, scale everything down to fit
    sx = (VB_W - 2 * MARGIN) / max_x if max_x > VB_W else 1.0
    sy = (VB_H - 2 * MARGIN) / max_y if max_y > VB_H else 1.0
    scale = min(sx, sy)  # Uniform scale to preserve aspect ratio
    offset_x = MARGIN if scale < 1.0 else 0.0
    offset_y = MARGIN if scale < 1.0 else 0.0

    def sc_x(v): return round(v * scale + offset_x, 2)
    def sc_y(v): return round(v * scale + offset_y, 2)
    def sc_w(v): return round(v * scale, 2)
    def sc_h(v): return round(v * scale, 2)
    def sc_fs(pt):
        """Scale font size (pt→mm, then apply coordinate scale)."""
        fs_mm = max(pt * 0.352778, 1.5)
        return round(max(fs_mm * scale, 1.2), 2)

    svg = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="420mm" height="297mm" viewBox="0 0 420 297" data-template="true" data-page-type="' + page_type + '">\n'
    svg += '  <defs><style>\n'
    svg += '    .element { cursor: grab; } .element:active { cursor: grabbing; }\n'
    svg += '    .ph { outline: 2px dashed #00f0ff; }\n'
    svg += '    .ghost-ref { pointer-events: none; }\n'
    svg += '    .zone-overlay { pointer-events: all; }\n'
    svg += '  </style></defs>\n'

    # Layer 1: Ghost reference (URL, not base64)
    svg += f'  <g id="ghost-layer" class="ghost-ref" opacity="0.3">\n'
    svg += f'    <image x="0" y="0" width="420" height="297" href="{ghost_image_url}"/>\n'
    svg += '  </g>\n'

    # Layer 2: Background zones
    bg_roles = {"accent_bar", "sidebar", "category_card", "section_bg"}
    svg += '  <g id="bg-zones-layer">\n'
    for z in sorted(zones, key=lambda z: z.get("z_order", 0)):
        if z.get("role") in bg_roles and z.get("bg_color"):
            b = z.get("bounds", {})
            x, y, w, h = sc_x(b.get("x_mm", 0)), sc_y(b.get("y_mm", 0)), sc_w(b.get("w_mm", 50)), sc_h(b.get("h_mm", 20))
            zid = z.get("id", "zone")
            role = z.get("role", "decoration")
            label = z.get("text_content", "")[:30].replace('"', '&quot;')
            svg += f'    <g id="{zid}" class="element selectable zone-overlay" data-id="{zid}" data-role="{role}" data-type="rect" data-zone-id="{zid}" data-label="{label}">\n'
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{z["bg_color"]}" opacity="0.7"/>\n'
            svg += '    </g>\n'
    svg += '  </g>\n'

    # Layer 3: Content zones
    svg += '  <g id="content-layer">\n'
    for z in sorted(zones, key=lambda z: z.get("z_order", 0)):
        if z.get("role") in bg_roles and z.get("bg_color"):
            continue

        b = z.get("bounds", {})
        x, y, w, h = sc_x(b.get("x_mm", 0)), sc_y(b.get("y_mm", 0)), sc_w(b.get("w_mm", 50)), sc_h(b.get("h_mm", 20))
        zid = z.get("id", "zone")
        role = z.get("role", "decoration")
        text = z.get("text_content", "")
        label = text[:30].replace('"', '&quot;') if text else role
        direction = z.get("text_direction", "horizontal")
        fg = z.get("fg_color") or "#000000"
        fs_pt = z.get("font_size_pt", 10)
        fs_mm = sc_fs(fs_pt)
        fw = "bold" if z.get("font_weight") == "bold" else "normal"

        svg += f'    <g id="{zid}" class="element selectable zone-overlay ph" data-id="{zid}" data-role="{role}" data-type="{"textblock" if text else "rect"}" data-zone-id="{zid}" data-label="{label}" data-direction="{direction}">\n'

        if role == "photo":
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#E0E0E0" stroke="#999" stroke-width="0.5" stroke-dasharray="2,2"/>\n'
            desc = text[:20] if text else "photo"
            svg += f'      <text x="{round(x + w/2, 1)}" y="{round(y + h/2, 1)}" font-family="YuGothic, sans-serif" font-size="{max(fs_mm, 2.5)}" fill="#666" text-anchor="middle" dominant-baseline="middle">[{desc}]</text>\n'
        elif text:
            if direction == "vertical":
                col_x = x + w - fs_mm * 1.2
                char_y = y + fs_mm
                for char in text[:100]:
                    if char == '\n' or char_y > y + h - fs_mm:
                        col_x -= fs_mm * 1.5
                        char_y = y + fs_mm
                        if col_x < x:
                            break
                    if char != '\n':
                        svg += f'      <text x="{round(col_x, 1)}" y="{round(char_y, 1)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs_mm}" font-weight="{fw}" fill="{fg}" text-anchor="middle">{char}</text>\n'
                        char_y += fs_mm * 1.3
            else:
                lines = text.split('\n') if '\n' in text else [text]
                line_h = fs_mm * 1.6
                ty = y + fs_mm
                for line in lines[:20]:
                    if ty > y + h:
                        break
                    safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    svg += f'      <text x="{x}" y="{round(ty, 1)}" font-family="YuGothic, \'Hiragino Sans\', sans-serif" font-size="{fs_mm}" font-weight="{fw}" fill="{fg}">{safe}</text>\n'
                    ty += line_h
        else:
            svg += f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#00f0ff" stroke-width="0.3" stroke-dasharray="2,1"/>\n'

        svg += '    </g>\n'
    svg += '  </g>\n'

    return svg + '</svg>'
