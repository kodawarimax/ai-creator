import os
import json
import logging
from flask import Blueprint, request, jsonify

templates_bp = Blueprint('templates', __name__)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'user_templates')
os.makedirs(TEMPLATES_DIR, exist_ok=True)

@templates_bp.route("/templates", methods=["GET"])
def list_templates():
    templates = []
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if not fname.endswith('.json'): continue
        fpath = os.path.join(TEMPLATES_DIR, fname)
        try:
            with open(fpath, 'r') as f:
                d = json.load(f)
                templates.append({
                    "id": fname[:-5],
                    "name": d.get("name", "Untitled"),
                    "page_count": len(d.get("pages", [])),
                    "created_at": d.get("created_at", "")
                })
        except: continue
    return jsonify(templates)

@templates_bp.route("/api/templates/", methods=["POST"])
@templates_bp.route("/templates", methods=["POST"])
def save_template():
    data = request.get_json()
    name = data.get("name", "My Template")
    pages = data.get("pages", [])
    import time
    tid = f"tmpl_{int(time.time())}"
    fpath = os.path.join(TEMPLATES_DIR, f"{tid}.json")
    
    template_data = {"name": name, "pages": pages, "created_at": time.ctime()}
    if data.get("design_spec"):
        template_data["design_spec"] = data["design_spec"]
    if data.get("page_types"):
        template_data["page_types"] = data["page_types"]

    with open(fpath, 'w') as f:
        json.dump(template_data, f, ensure_ascii=False)

    return jsonify({"id": tid, "name": name, "page_count": len(pages)})

@templates_bp.route("/templates/<tid>", methods=["GET"])
def get_template(tid):
    fpath = os.path.join(TEMPLATES_DIR, f"{tid}.json")
    if not os.path.exists(fpath): return jsonify({"error": "Not found"}), 404
    with open(fpath, 'r') as f: return jsonify(json.load(f))

@templates_bp.route("/templates/<tid>", methods=["DELETE"])
def delete_template(tid):
    fpath = os.path.join(TEMPLATES_DIR, f"{tid}.json")
    if os.path.exists(fpath): os.remove(fpath)
    return jsonify({"success": True})
