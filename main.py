import os
from flask import Flask, jsonify
from flask_cors import CORS

def create_app():
    app = Flask(__name__, static_folder='.', static_url_path='')
    CORS(app, origins=["http://localhost:5173", "http://localhost:5174", "https://kodawarimax.github.io", "http://72.61.119.101"])

    # Register Blueprints (to be created)
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
        return jsonify({"status": "healthy", "version": "2.0.0-god-tier"})

    return app

app = create_app()

if __name__ == '__main__':
    # Using Port 5051 as per the God Tier plan
    app.run(host='0.0.0.0', port=5051, debug=True)
