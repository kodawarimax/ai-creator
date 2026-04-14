import os
import json
import logging
from flask import Blueprint, request, jsonify
from google import genai
from google.genai import types as genai_types

ai_magic_bp = Blueprint('ai_magic', __name__)
logger = logging.getLogger(__name__)

# Config
GEMINI_MODEL = "gemini-2.0-flash"

def _get_client():
    apiKey = os.environ.get("GEMINI_API_KEY", "")
    return genai.Client(api_key=apiKey)

def _clean_json(text):
    import re
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text).strip()
    return text

@ai_magic_bp.route('/autofill', methods=['POST'])
def autofill_content():
    """
    AI Producer Core: Autofills all placeholders across multiple pages
    based on a single global theme prompt.
    """
    try:
        client = _get_client()
        data = request.json or {}
        theme = data.get('theme', 'General Magazine')
        elements = data.get('elements', []) # List of {id, role, current_text, label}
        
        if not elements:
            return jsonify({"error": "No elements provided"}), 400

        prompt = f"""
        You are a Professional Magazine Editor.
        Global Theme: "{theme}"
        
        Tasks:
        1. Rewrite the content for EVERY element provided below to fit the global theme.
        2. Maintain the TONE of a high-end publication.
        3. Keep text lengths appropriate for their roles (headlines short, body paragraphs descriptive).
        4. Output a JSON object mapping element 'id' to 'new_content'.
        
        Elements to Fill:
        {json.dumps(elements, ensure_ascii=False)}
        
        Expected Output Format:
        {{
          "results": [
            {{ "id": "textblock_1", "content": "New Headline Here" }},
            ...
          ]
        }}
        """

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        result_data = json.loads(_clean_json(response.text))
        return jsonify(result_data)

    except Exception as e:
        logger.error(f"Autofill Failed: {e}")
        return jsonify({"error": str(e)}), 500

@ai_magic_bp.route('/generate-image', methods=['POST'])
def generate_image_asset():
    """
    AI Image Production: Generates context-aware images for placeholders.
    """
    try:
        client = _get_client()
        data = request.json or {}
        prompt_suffix = data.get('prompt', 'Modern magazine photography')
        role = data.get('role', 'photo')
        
        # Note: Using Gemini Pro Vision for description if needed, 
        # but here we generate a prompt for an imaginer.
        # For now, we'll return a high-quality prompt that the frontend 
        # can eventually use with an Imagen tool or Unsplash.
        
        image_prompt = f"Professional {role} photography: {prompt_suffix}. High resolution, 8k, magazine style."
        
        # If Imagen 3/4 is available in the SDK:
        # response = client.models.generate_image(model="imagen-3.0-generate-001", prompt=image_prompt)
        
        return jsonify({
            "status": "success",
            "prompt": image_prompt,
            "mock_url": f"https://source.unsplash.com/featured/?{prompt_suffix.replace(' ', ',')}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
