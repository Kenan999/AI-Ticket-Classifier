"""Local Shoply customer chat API and static frontend server.

Run: python3 -m backend.chat.api --port 8016
Uses the existing results/live_chat.sqlite.
"""
import argparse
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'results' / 'live_chat.sqlite'
PUBLIC = ROOT / 'public'
ACTIVE = ('active', 'processing', 'shipped')
sys.path.insert(0, str(ROOT))
from backend.chat.service import reply as chat_reply
from backend.chat import live_support, provider as chat_provider
from backend.review_threshold import get_threshold, set_threshold


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1:8015')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def json_response(self,status,result):
        body=json.dumps(result).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:8015')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path=urlsplit(self.path).path
        if path not in ('/api/chat/reply','/api/support/request','/api/support/accept','/api/support/message','/api/support/close','/api/support/reset-demo','/api/chat/provider','/api/chat/tickets','/api/chat/tickets/status','/api/chat/tickets/dismiss','/api/review-threshold'):
            self.send_error(404);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Invalid request')
            if path=='/api/chat/reply':result=chat_reply(data.get('session_id'),data.get('message'),data.get('order_number'))
            elif path=='/api/chat/provider':result=chat_provider.set_provider(data.get('provider'))
            elif path=='/api/review-threshold':result={'threshold':set_threshold(data.get('threshold'))}
            elif path=='/api/chat/tickets':result=live_support.start_chat_ticket(data.get('message'))
            elif path=='/api/chat/tickets/status':result=live_support.update_chat_ticket(data.get('id'),data.get('status'),data.get('category'),data.get('confidence'))
            elif path=='/api/chat/tickets/dismiss':result=live_support.dismiss_chat_ticket(data.get('id'))
            elif path=='/api/support/request':result=live_support.create(data.get('history'),data.get('ticket_id'))
            elif path=='/api/support/accept':result=live_support.accept(data.get('id'))
            elif path=='/api/support/message':
                sender=data.get('sender')
                if sender not in ('customer','employee'):raise ValueError('Invalid sender')
                result=live_support.message(data.get('id'),sender,data.get('message'),data.get('customer_token'))
            elif path=='/api/support/reset-demo':result=live_support.close_open_demo_sessions()
            else:result=live_support.close(data.get('id'),data.get('customer_token'),data.get('staff') is True)
            self.json_response(200,result)
        except (ValueError,KeyError) as exc:self.json_response(400,{'error':str(exc)})
        except LookupError:self.json_response(404,{'error':'Chat not found'})
        except Exception as exc:
            print('Chat API error:',repr(exc),file=sys.stderr)
            self.json_response(502,{'error':'Chat service unavailable'})

    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/api/chat/status':
            from backend.chat.connectivity import statuses
            return self.json_response(200, statuses())
        if parsed.path=='/api/chat/provider':
            config=__import__('backend.chat.service',fromlist=['settings']).settings()
            import os
            return self.json_response(200,{'provider':chat_provider.get(),'providers':[{'id':'gemini','configured':bool(os.getenv('GEMINI_API_KEY') or config.get('GEMINI_API_KEY'))},{'id':'openai','configured':bool(os.getenv('OPENAI_API_KEY') or config.get('OPENAI_API_KEY'))},{'id':'local','configured':__import__('socket').socket().connect_ex(('127.0.0.1',18642))==0}]})
        if parsed.path=='/api/review-threshold':
            return self.json_response(200,{'threshold':get_threshold()})
        if parsed.path=='/api/chat/tickets':
            return self.json_response(200,live_support.chat_tickets())
        if parsed.path=='/api/support/queue':
            return self.json_response(200,live_support.queue())
        if parsed.path=='/api/support/session':
            args=parse_qs(parsed.query)
            try:
                return self.json_response(200,live_support.read(args.get('id',[''])[0],args.get('customer_token',[None])[0],args.get('staff',['0'])[0]=='1'))
            except LookupError:return self.json_response(404,{'error':'Chat not found'})
        return super().do_GET()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8016)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
