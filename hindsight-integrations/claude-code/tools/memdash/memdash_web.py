#!/usr/bin/env python3
"""memdash 웹 대시보드 — 실시간 주기 갱신 + WebGL 연결 그래프.

Usage: ./memdash_web.py [--port 9090]
브라우저에서 http://localhost:9090 접속. 요약은 10초, 그래프는 60초 주기 갱신.
"""

import argparse
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import memdash

DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 조용히
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                html = open(os.path.join(DIR, "memdash_web.html"), "rb").read()
                self._send(200, html, "text/html")
            elif u.path == "/api/summary":
                bench = q.get("bench", ["0"])[0] == "1"
                d = memdash.collect(bench_n=5 if bench else 0)
                d["history"] = memdash.load_history()[-20:]
                self._send(200, json.dumps(d, ensure_ascii=False).encode())
            else:
                self._send(404, b"{}")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}).encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9090)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"memdash web: http://localhost:{args.port}  (Ctrl-C로 종료)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
