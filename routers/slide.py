import os
import json
import base64
import subprocess
import tempfile
import logging
from flask import Blueprint, request, jsonify
from google import genai
from google.genai import types as genai_types

slide_bp = Blueprint('slide', __name__)
logger = logging.getLogger(__name__)

def _get_client():
    apiKey = os.environ.get("GEMINI_API_KEY", "")
    try:
        return genai.Client(api_key=apiKey, http_options={'api_version': 'v1alpha'})
    except Exception as e:
        logger.warning(f"GenAI Client Init Failed: {e}")
        return None

NLM_PATH = "/Users/jungosakamoto/.local/bin/nlm"

# --- Utility ---
def _run_nlm(args, timeout=120):
    result = subprocess.run([NLM_PATH] + args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result

def _extract_id(output, keyword="ID:"):
    for line in output.splitlines():
        if keyword in line: return line.split(keyword)[-1].strip()
    return output.strip().splitlines()[-1].strip()

# --- Handlers ---
@slide_bp.route("/revise", methods=["POST"])
def analyze_brand():
    data = request.get_json()
    b64 = data.get("image", "").split(",")[-1]
    prompt = "Analyze the branding in this image and output a style YAML: fonts, colors, tone, etc."
    
    client = _get_client()
    if not client: return jsonify({"error": "Gemini Client not initialized. Check API Key."}), 500
    resp = client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=[genai_types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/png"), prompt],
        config=genai_types.GenerateContentConfig(response_mime_type="application/yaml")
    )
    return jsonify({"yaml": resp.text})

@slide_bp.route("/create", methods=["POST"])
def create_slide():
    data = request.get_json()
    title = data.get("title", "Presentation")
    
    # 1. Create Notebook
    r1 = _run_nlm(["notebook", "create", title])
    nb_id = _extract_id(r1.stdout)
    
    # 2. Add Source
    _run_nlm(["source", "add", nb_id, "--text", data.get("content", ""), "--title", f"{title} Source", "--wait"])
    
    # 3. Create Slides
    r3 = _run_nlm(["slides", "create", nb_id, "--format", data.get("format", "detailed_deck"), "-y"])
    art_id = _extract_id(r3.stdout, "Artifact ID:")
    
    return jsonify({
        "notebook_id": nb_id,
        "artifact_id": art_id,
        "notebook_url": f"https://notebooklm.google.com/notebook/{nb_id}",
        "message": "Presentation generation initialized."
    })

@slide_bp.route("/status", methods=["POST"])
def get_status():
    data = request.get_json()
    r = _run_nlm(["studio", "status", data.get("notebook_id"), "--json"])
    return jsonify({"artifacts": json.loads(r.stdout)})

@slide_bp.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    nb_id = data.get("notebook_id")
    fmt = data.get("format", "pdf")
    art_id = data.get("artifact_id")

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, f"slides.{fmt}")
        args = ["download", "slide-deck", nb_id, "-o", out, "--format", fmt, "--no-progress"]
        if art_id: args += ["--id", art_id]
        _run_nlm(args)
        with open(out, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
            
    mime = "application/pdf" if fmt == "pdf" else "application/vnd.ms-powerpoint"
    return jsonify({"file": f"data:{mime};base64,{b64}", "filename": f"presentation.{fmt}"})
