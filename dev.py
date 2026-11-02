"""Local server: python3 dev.py  ->  http://localhost:8000  (needs the 3 env vars, see README)"""
import os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
sys.path.insert(0, "api")
from backtest import handler as Api

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory="public", **k)
    def do_POST(self): Api.do_POST(self) if self.path == "/api/backtest" else self.send_error(404)
    _send = Api._send

if __name__ == "__main__":
    print("http://localhost:8000"); HTTPServer(("127.0.0.1", 8000), H).serve_forever()
