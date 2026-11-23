import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from backend.rag.local.server import make_handler

class LocalServerTests(unittest.TestCase):
    def test_embedding_and_health(self):
        with patch('backend.rag.local.server.encode', return_value=[[0.1, 0.2]]) as encode:
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(object()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'http://127.0.0.1:' + str(server.server_port)
                with urlopen(url + '/health') as r:
                    self.assertEqual(json.load(r)['status'], 'ok')
                payload = {'model': 'multilingual-e5-small', 'input': 'hello', 'task_type': 'RETRIEVAL_QUERY'}
                req = Request(url + '/v1/embeddings', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
                with urlopen(req) as r:
                    self.assertEqual(json.load(r)['data'][0]['embedding'], [0.1, 0.2])
                encode.assert_called_once()
                self.assertEqual(encode.call_args.args[1], ['query: hello'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
