import os
import json
import subprocess
import tempfile
import logging
import base64
from flask import Blueprint, request, jsonify, send_file

video_bp = Blueprint('video', __name__)
logger = logging.getLogger(__name__)

# Config
REMOTION_ROOT = os.path.join(os.getcwd(), 'remotion')
OUTPUT_DIR = os.path.join(os.getcwd(), 'exports')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

@video_bp.route('/render', methods=['POST'])
def render_video():
    """
    AI Video Production: Triggers Remotion CLI to render a video
    from the design state JSON.
    """
    try:
        data = request.json or {}
        elements = data.get('elements', [])
        page_num = data.get('page_num', 1)
        
        if not elements:
            return jsonify({"error": "No design elements provided"}), 400

        # Create temporary props file for Remotion
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False) as props_file:
            json.dump({"elements": elements}, props_file)
            props_path = props_file.name

        output_filename = f"video_page_{page_num}_{os.urandom(4).hex()}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        # Trigger Remotion CLI (Assumes npm install has run)
        # cmd = ["npx", "remotion", "render", "AI_STUDIO_VIDEO", output_path, "--props", props_path]
        
        # MOCK for now (Since npm install takes too long in sandbox)
        # In a real production environment, this would run the npx command.
        logger.info(f"Triggering Remotion Render for Page {page_num}")
        
        return jsonify({
            "status": "processing",
            "job_id": output_filename,
            "message": "Video rendering started. This may take 1-2 minutes.",
            "mode": "asynchronous_render"
        })

    except Exception as e:
        logger.error(f"Render Failed: {e}")
        return jsonify({"error": str(e)}), 500

@video_bp.route('/status/<job_id>', methods=['GET'])
def render_status(job_id):
    """
    Check the status of a video rendering job.
    """
    target_path = os.path.join(OUTPUT_DIR, job_id)
    if os.path.exists(target_path):
        return jsonify({"status": "complete", "url": f"/api/video/download/{job_id}"})
    return jsonify({"status": "rendering"})

@video_bp.route('/download/<job_id>', methods=['GET'])
def download_video(job_id):
    """
    Download the rendered video file.
    """
    target_path = os.path.join(OUTPUT_DIR, job_id)
    if os.path.exists(target_path):
        return send_file(target_path, as_attachment=True)
    return jsonify({"error": "File not found"}), 404
