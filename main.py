import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

API_TOKEN = os.environ.get('API_ACCESS_TOKEN', '').strip()
AUTH_EXEMPT_PATHS = {'/', '/health'}

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'FRONTEND_ORIGINS',
        'http://localhost:5173,http://localhost:5174,https://kodawarimax.github.io,https://srv1334941.hstgr.cloud'
    ).split(',')
    if origin.strip()
]


def create_app():
    app = Flask(__name__, static_folder='.', static_url_path='')
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB upload cap

    CORS(
        app,
        origins=ALLOWED_ORIGINS,
        allow_headers=['Content-Type', 'X-API-Token', 'Authorization'],
        methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    )

    Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=['300 per hour', '60 per minute'],
        storage_uri='memory://',
        strategy='fixed-window',
    )

    @app.before_request
    def require_api_token():
        if request.method == 'OPTIONS':
            return None
        if request.path in AUTH_EXEMPT_PATHS or not request.path.startswith('/api/'):
            return None
        if not API_TOKEN:
            logger.warning('API_ACCESS_TOKEN is not set — /api endpoints are UNAUTHENTICATED (development mode)')
            return None
        provided = request.headers.get('X-API-Token', '').strip()
        if provided != API_TOKEN:
            return jsonify({'error': 'unauthorized', 'message': 'invalid or missing X-API-Token'}), 401
        return None

    from routers.manga import manga_bp
    from routers.slide import slide_bp
    from routers.design import design_bp
    from routers.templates import templates_bp
    from routers.ai_magic import ai_magic_bp
    from routers.video import video_bp

    app.register_blueprint(manga_bp, url_prefix='/api')
    app.register_blueprint(slide_bp, url_prefix='/api/slide')
    app.register_blueprint(design_bp, url_prefix='/api/design')
    app.register_blueprint(templates_bp, url_prefix='/api')
    app.register_blueprint(ai_magic_bp, url_prefix='/api/magic')
    app.register_blueprint(video_bp, url_prefix='/api/video')

    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'version': os.environ.get('APP_VERSION', '2.1.0'),
            'auth_enabled': bool(API_TOKEN),
        })

    @app.errorhandler(413)
    def payload_too_large(_e):
        return jsonify({'error': 'payload_too_large', 'message': 'file exceeds 50MB limit'}), 413

    @app.errorhandler(429)
    def rate_limited(_e):
        return jsonify({'error': 'rate_limited', 'message': 'too many requests'}), 429

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5051, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
