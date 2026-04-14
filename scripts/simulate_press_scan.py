import fitz
import os
import json
import logging
from google import genai
from google.genai import types as genai_types

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "press_231.pdf")
API_KEY = "AIzaSyBOACATQt2uLZx7GR4Bn8HWHrShqka2UKI"
DPI = 300

def simulate_scan():
    doc = fitz.open(PDF_PATH)
    page = doc[0] # Test Page 1 (Cover/Contents)
    
    # 1. Native Extraction (Skeleton)
    logger.info("Extracting native text and structure...")
    text_dict = page.get_text("dict")
    
    # 2. Vector Extraction (Paths)
    paths = page.get_drawings()
    logger.info(f"Captured {len(paths)} vector paths.")
    
    # 3. AI Semantic Analysis (Simulation)
    logger.info("Connecting to Gemini for semantic layout analysis...")
    client = genai.Client(api_key=API_KEY)
    
    # Create screenshot for AI context
    pix = page.get_pixmap(dpi=DPI)
    img_data = pix.tobytes("png")
    
    prompt = """
    Analyze this magazine page and identify structural components for a design template.
    Output JSON: { "elements": [ { "id": "el_1", "role": "headline", "label": "Title", "group_id": "header" }, ... ] }
    Focus on grouping related text spans and identifying vector icons.
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=img_data, mime_type="image/png")
            ],
            config=genai_types.GenerateContentConfig(response_mime_type="application/json")
        )
        analysis = json.loads(response.text)
        logger.info(f"AI Analysis Complete: Found {len(analysis.get('elements', []))} semantic elements.")
        
        # 4. Result Validation
        result = {
            "page_info": { "width": page.rect.width, "height": page.rect.height },
            "native_stats": { "text_blocks": len(text_dict["blocks"]), "paths": len(paths) },
            "ai_suggestions": analysis
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    except Exception as e:
        logger.error(f"Scan failed: {e}")

if __name__ == "__main__":
    simulate_scan()
