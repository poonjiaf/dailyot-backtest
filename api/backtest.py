import hmac, json, os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _core


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw or not hmac.compare_digest(self.headers.get("x-app-password", ""), pw):
            return self._send(401, {"error": "wrong or missing password"})
        try:
            p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            res = _core.run(p)
            if p.get("save"):
                res["run_id"] = _core.save_run(res)
            self._send(200, res)
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
