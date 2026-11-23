"""Loopback-only, project-owned OpenAI-compatible embedding HTTP service."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, MODEL_NAME
from .model_loader import load_model, encode


def make_handler(model):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                return self.respond(200, {'status': 'ok', 'model': MODEL_NAME})
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            if self.path != '/v1/embeddings':
                return self.respond(404, {'error': 'Not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 100000:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or payload.get('model') != MODEL_NAME:
                    raise ValueError('Unknown embedding model')
                texts = payload.get('input')
                texts = [texts] if isinstance(texts, str) else texts
                if not isinstance(texts, list) or not 1 <= len(texts) <= 32 or any(not isinstance(t, str) or not t.strip() or len(t) > 12000 for t in texts):
                    raise ValueError('Expected 1–32 nonempty text inputs')
                # E5 requires asymmetric prefixes for document and query encoding.
                kind = payload.get('task_type', 'RETRIEVAL_DOCUMENT')
                if kind not in ('RETRIEVAL_DOCUMENT', 'RETRIEVAL_QUERY'):
                    raise ValueError('Invalid task type')
                prefix = 'query: ' if kind == 'RETRIEVAL_QUERY' else 'passage: '
                vectors = encode(model, [prefix + t for t in texts])
                return self.respond(200, {'object': 'list', 'model': MODEL_NAME,
                    'data': [{'object': 'embedding', 'index': i, 'embedding': vector} for i, vector in enumerate(vectors)]})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                return self.respond(400, {'error': str(exc)})
            except Exception:
                return self.respond(500, {'error': 'Embedding failed'})

        def respond(self, status, payload):
            data = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve():
    model = load_model()
    with ThreadingHTTPServer((HOST, PORT), make_handler(model)) as server:
        print(f'Local embeddings ready at http://{HOST}:{PORT}/v1/embeddings', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    serve()
