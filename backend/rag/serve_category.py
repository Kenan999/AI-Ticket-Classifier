"""Run isolated RAG classification endpoint without replacing existing classifier API."""
import os
from backend.app import create_app

if __name__ == '__main__':
    os.environ.setdefault('FRONTEND_ORIGINS', 'http://127.0.0.1:8015,http://localhost:8015')
    create_app().run(host='127.0.0.1', port=8002, debug=False)
