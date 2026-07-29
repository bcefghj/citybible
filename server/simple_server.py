#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城设 CityBible · 标准库兜底服务器（零第三方依赖）

存在的理由：部署环境若装不上 FastAPI/uvicorn（内网、无 pip 源、被网关拦），
这一份仍能提供完整的 REST + MCP 能力，展示页与 Demo 不受影响。
deploy.sh 会优先用 uvicorn，失败则自动切到这里。

  python3 -m server.simple_server --port 8766
"""
from __future__ import annotations
import os, sys, json, pathlib, argparse, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import core  # noqa: E402

WEB = ROOT / "web"


class H(BaseHTTPRequestHandler):
    server_version = "CityBible/0.1"

    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _file(self, p: pathlib.Path):
        if not p.is_file():
            return self._send({"error": "not found"}, 404)
        t = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        b = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", t)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); path = u.path; q = parse_qs(u.query)
        if path in ("/api/health", "/health"):
            return self._send(core.health())
        if path == "/api/landmarks":
            return self._send({"count": len(core.MANIFEST), "landmarks": core.landmarks()})
        if path == "/api/asset":
            r = core.do_query_asset((q.get("landmark") or [""])[0])
            return self._send(r, 404 if "error" in r else 200)
        if path == "/api/cases":
            return self._send(core.CASES)
        if path == "/api/calibration":
            return self._send(core.calibration())
        if path in ("/", "/index.html", "/citybible/", "/citybible/index.html"):
            return self._file(WEB / "index.html")
        # 静态资源
        rel = path.lstrip("/").replace("citybible/", "", 1)
        cand = (WEB / rel).resolve()
        if str(cand).startswith(str(WEB.resolve())):
            return self._file(cand)
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/mcp":
            return self._send({"error": "not found"}, 404)
        if core.TOKEN and self.headers.get("Authorization", "") != "Bearer " + core.TOKEN:
            return self._send({"error": "unauthorized"}, 401)
        origin = self.headers.get("Origin")
        if origin and not (origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")):
            return self._send({"error": "origin not allowed"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send({"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32700, "message": "JSON 解析失败"}}, 400)
        return self._send(core.mcp_dispatch(body))

    def log_message(self, fmt, *a):
        sys.stderr.write("[cb] " + fmt % a + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("CITYBIBLE_PORT", 8766)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print("城设 CityBible （标准库模式）  http://%s:%d/" % (a.host, a.port))
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
